import pandas as pd
import streamlit as st
from utils import ADMIN_PASSWORD, now_ec_str, sort_camiones, upsert_status_records
import re
import unicodedata


def _norm_text(s: str) -> str:
    s = str(s).upper().strip()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _match_cod_paquete(cod_str: str, q_num: int) -> bool:
    nums = [int(x) for x in re.findall(r"\d+", str(cod_str))]
    if len(nums) >= 2:
        return nums[0] <= q_num <= nums[-1]
    if len(nums) == 1:
        return nums[0] == q_num
    return False

def _reset_ent_filtros():
    st.session_state["e_fz"] = "TODAS"
    st.session_state["e_gt"] = "TODOS"
    st.session_state["e_cam"] = "TODOS"
    st.session_state["e_est"] = "TODOS"
    st.session_state["e_busq_recinto"] = ""


def _on_e_fz_change():
    st.session_state["e_gt"] = "TODOS"
    st.session_state["e_cam"] = "TODOS"
    st.session_state["e_busq_recinto"] = ""


def _reset_rec_filtros():
    st.session_state["r_fz"] = "TODAS"
    st.session_state["r_gt"] = "TODOS"
    st.session_state["r_cam"] = "TODOS"
    st.session_state["r_est"] = "TODOS"
    st.session_state["r_busq_recinto"] = ""


def _on_r_fz_change():
    st.session_state["r_gt"] = "TODOS"
    st.session_state["r_cam"] = "TODOS"
    st.session_state["r_busq_recinto"] = ""


def render(df_all: pd.DataFrame):
    st.subheader("Control Operativo de Bodega CNE — Despacho y Retorno")

    if "auth_ok" not in st.session_state:
        st.session_state["auth_ok"] = False

    if not st.session_state["auth_ok"]:
        st.info("🔒 Esta sección está restringida al personal de control de bodega. Ingrese la clave para registrar entregas y recepciones.")
        col_pw, col_btn = st.columns([2, 1])
        pwd_in = col_pw.text_input("Clave de acceso", type="password", key="pwd_input")
        if col_btn.button("Ingresar", type="primary", use_container_width=True):
            if pwd_in == ADMIN_PASSWORD:
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Clave incorrecta.")
        return

    top_a, top_b = st.columns([4, 1])
    operador = top_a.text_input(
        "Nombre / Grado del operador que registra",
        value=st.session_state.get("operador", "Bodega Base Naval Sur"),
        key="op_name",
    )
    st.session_state["operador"] = operador
    if top_b.button("🔒 Cerrar sesión", use_container_width=True):
        st.session_state["auth_ok"] = False
        st.rerun()

    modo_ctrl = st.radio(
        "Etapa operativa:",
        [
            "🚚 Despacho desde Bodega a Jefes De Recinto",
            "📦 Recibido en Bodega — Post-Elecciones",
        ],
        horizontal=True,
        key="ctrl_modo",
    )

    if modo_ctrl.startswith("🚚"):
        fc1, fc2, fc3, fc4, fc5 = st.columns([1.1, 1.0, 1.0, 1.1, 0.9])
        fuerzas_e = ["TODAS"] + sorted(df_all["FUERZA"].unique().tolist())
        e_fz = fc1.selectbox("Fuerza", fuerzas_e, key="e_fz", on_change=_on_e_fz_change)
        df_e = df_all if e_fz == "TODAS" else df_all[df_all["FUERZA"] == e_fz]

        e_gt_opts = ["TODOS"] + sorted([x for x in df_e["GT"].unique().tolist() if x])
        if st.session_state.get("e_gt", "TODOS") not in e_gt_opts:
            st.session_state["e_gt"] = "TODOS"
        e_gt = fc2.selectbox("GT", e_gt_opts, key="e_gt")
        if e_gt != "TODOS":
            df_e = df_e[df_e["GT"] == e_gt]

        e_cam_opts = ["TODOS"] + sort_camiones(df_e["CAMION"].unique().tolist())
        if st.session_state.get("e_cam", "TODOS") not in e_cam_opts:
            st.session_state["e_cam"] = "TODOS"
        e_cam = fc3.selectbox("Camión", e_cam_opts, key="e_cam")
        if e_cam != "TODOS":
            df_e = df_e[df_e["CAMION"] == e_cam]

        e_est = fc4.selectbox("Estado Entrega", ["TODOS", "Pendientes", "Entregados"], key="e_est")
        if e_est == "Pendientes":
            df_e = df_e[~df_e["ENTREGADO"]]
        elif e_est == "Entregados":
            df_e = df_e[df_e["ENTREGADO"]]

        with fc5:
            st.write("")
            st.button("🧹 Limpiar", use_container_width=True, key="btn_limpiar_e", on_click=_reset_ent_filtros)

        e_busq = st.text_input(
            "🔎 Buscar por nombre de Recinto, Zona o Código de Paquete",
            placeholder="Escriba parte del nombre del recinto (Ej: MILAGRO, 9 DE OCTUBRE, ROCAFUERTE...)",
            key="e_busq_recinto",
        )
        if e_busq.strip():
            q_raw = e_busq.strip()
            q = _norm_text(q_raw)
            mask_e = (
                df_e["RECINTO"].apply(_norm_text).str.contains(q, na=False, regex=False)
                | df_e["ZONA"].apply(_norm_text).str.contains(q, na=False, regex=False)
                | df_e["CANTON"].apply(_norm_text).str.contains(q, na=False, regex=False)
                | df_e["PARROQUIA"].apply(_norm_text).str.contains(q, na=False, regex=False)
                | df_e["CODIGO PAQUETES"].apply(_norm_text).str.contains(q, na=False, regex=False)
                | df_e["CODIGO KIT CDA"].apply(_norm_text).str.contains(q, na=False, regex=False)
            )
            if q_raw.isdigit():
                q_num = int(q_raw)
                mask_e = mask_e | df_e["CODIGO PAQUETES"].apply(lambda x: _match_cod_paquete(x, q_num))
            df_e = df_e[mask_e]

        if qa2.button(
            f"✅ Marcar {len(df_e)} recinto(s) como ENTREGADO",
            type="primary",
            use_container_width=True,
            disabled=(len(df_e) == 0),
        ):
            ts = now_ec_str()
            recs = []
            for _, r in df_e.iterrows():
                recs.append(
                    {
                        "orden": int(r["ORDEN"]),
                        "entregado": 1,
                        "fecha_hora_entrega": r["FECHA_HORA_ENTREGA"] if r["ENTREGADO"] and r["FECHA_HORA_ENTREGA"] else ts,
                        "usuario_entrega": operador,
                        "obs_entrega": obs_lote if obs_lote else r["OBS_ENTREGA"],
                        "recibido_bodega": int(bool(r["RECIBIDO_BODEGA"])),
                        "fecha_hora_finalizacion": r["FECHA Y HORA DE FINALIZACION"],
                        "usuario_recepcion": r["USUARIO_RECEPCION"],
                        "obs_recepcion": r["OBS_RECEPCION"],
                    }
                )
            upsert_status_records(recs)
            st.success(f"Se marcaron {len(recs)} recintos como ENTREGADO ({ts}).")
            st.rerun()

        if qa3.button("↩️ Revertir a PENDIENTE", use_container_width=True, disabled=(len(df_e) == 0)):
            recs = []
            for _, r in df_e.iterrows():
                recs.append(
                    {
                        "orden": int(r["ORDEN"]),
                        "entregado": 0,
                        "fecha_hora_entrega": "",
                        "usuario_entrega": "",
                        "obs_entrega": "",
                        "recibido_bodega": 0,
                        "fecha_hora_finalizacion": "",
                        "usuario_recepcion": "",
                        "obs_recepcion": "",
                    }
                )
            upsert_status_records(recs)
            st.warning(f"Se revirtieron {len(recs)} recintos a PENDIENTE.")
            st.rerun()

        st.markdown("##### 📋 Edición individual por recinto")
        edit_cols = [
            "ORDEN", "ENTREGADO", "FECHA_HORA_ENTREGA", "OBS_ENTREGA",
            "DIA_ENTREGA", "HORA_STR", "FUERZA", "GT", "CAMION",
            "CANTON", "ZONA", "RECINTO", "NUMERO DE PAQUETES",
            "CODIGO PAQUETES", "CODIGO KIT CDA", "PERCHA", "NIVEL (POR PERCHA)",
        ]
        edited_ent = st.data_editor(
            df_e[edit_cols],
            use_container_width=True,
            hide_index=True,
            height=420,
            disabled=[c for c in edit_cols if c not in ("ENTREGADO", "OBS_ENTREGA")],
            column_config={
                "ENTREGADO": st.column_config.CheckboxColumn("ENTREGADO", default=False),
                "OBS_ENTREGA": st.column_config.TextColumn("Observación Entrega"),
                "FECHA_HORA_ENTREGA": st.column_config.TextColumn("Fecha/Hora Entrega"),
                "HORA_STR": st.column_config.TextColumn("Hora Prog."),
            },
            key="editor_entregas",
        )
        if st.button("💾 Guardar cambios individuales de Entrega", type="primary", key="save_ent_ind"):
            ts = now_ec_str()
            orig_map = df_e.set_index("ORDEN").to_dict("index")
            to_save = []
            for _, row_ed in edited_ent.iterrows():
                o_id = int(row_ed["ORDEN"])
                o_prev = orig_map[o_id]
                new_ent = bool(row_ed["ENTREGADO"])
                new_obs = str(row_ed["OBS_ENTREGA"] or "")
                if new_ent != bool(o_prev["ENTREGADO"]) or new_obs != str(o_prev["OBS_ENTREGA"]):
                    to_save.append(
                        {
                            "orden": o_id,
                            "entregado": int(new_ent),
                            "fecha_hora_entrega": (o_prev["FECHA_HORA_ENTREGA"] or ts) if new_ent else "",
                            "usuario_entrega": operador if new_ent else "",
                            "obs_entrega": new_obs if new_ent else "",
                            "recibido_bodega": int(bool(o_prev["RECIBIDO_BODEGA"])) if new_ent else 0,
                            "fecha_hora_finalizacion": o_prev["FECHA Y HORA DE FINALIZACION"] if new_ent else "",
                            "usuario_recepcion": o_prev["USUARIO_RECEPCION"] if new_ent else "",
                            "obs_recepcion": o_prev["OBS_RECEPCION"] if new_ent else "",
                        }
                    )
            if to_save:
                upsert_status_records(to_save)
                st.success(f"Guardados {len(to_save)} cambios de entrega.")
                st.rerun()
            else:
                st.info("No se detectaron cambios pendientes por guardar.")

    else:
        df_entregados = df_all[df_all["ENTREGADO"]].copy()
        if len(df_entregados) == 0:
            st.warning(
                "🔒 Todavía no hay recintos marcados como **ENTREGADO**. "
                "La recepción en bodega (post-elecciones) se habilita automáticamente únicamente para los recintos que ya fueron entregados."
            )
            return

        st.caption(
            f"Habilitados para retorno a bodega: **{len(df_entregados)}** recintos entregados "
            f"(de {len(df_all)} totales). Los recintos aún no entregados permanecen bloqueados."
        )
        rc1, rc2, rc3, rc4, rc5 = st.columns([1.1, 1.0, 1.0, 1.1, 0.9])
        fuerzas_r = ["TODAS"] + sorted(df_entregados["FUERZA"].unique().tolist())
        r_fz = rc1.selectbox("Fuerza", fuerzas_r, key="r_fz", on_change=_on_r_fz_change)
        df_r = df_entregados if r_fz == "TODAS" else df_entregados[df_entregados["FUERZA"] == r_fz]

        r_gt_opts = ["TODOS"] + sorted([x for x in df_r["GT"].unique().tolist() if x])
        if st.session_state.get("r_gt", "TODOS") not in r_gt_opts:
            st.session_state["r_gt"] = "TODOS"
        r_gt = rc2.selectbox("GT", r_gt_opts, key="r_gt")
        if r_gt != "TODOS":
            df_r = df_r[df_r["GT"] == r_gt]

        r_cam_opts = ["TODOS"] + sort_camiones(df_r["CAMION"].unique().tolist())
        if st.session_state.get("r_cam", "TODOS") not in r_cam_opts:
            st.session_state["r_cam"] = "TODOS"
        r_cam = rc3.selectbox("Camión", r_cam_opts, key="r_cam")
        if r_cam != "TODOS":
            df_r = df_r[df_r["CAMION"] == r_cam]

        r_est = rc4.selectbox("Estado Retorno", ["TODOS", "Por recibir", "Recibidos en Bodega"], key="r_est")
        if r_est == "Por recibir":
            df_r = df_r[~df_r["RECIBIDO_BODEGA"]]
        elif r_est == "Recibidos en Bodega":
            df_r = df_r[df_r["RECIBIDO_BODEGA"]]

        with rc5:
            st.write("")
            st.button("🧹 Limpiar", use_container_width=True, key="btn_limpiar_r", on_click=_reset_rec_filtros)

        r_busq = st.text_input(
            "🔎 Buscar por nombre de Recinto, Zona o Código de Paquete",
            placeholder="Escriba parte del nombre del recinto (Ej: MILAGRO, 9 DE OCTUBRE, ROCAFUERTE...)",
            key="r_busq_recinto",
        )
        if r_busq.strip():
            q = r_busq.strip().upper()
            df_r = df_r[
                df_r["RECINTO"].str.upper().str.contains(q, na=False)
                | df_r["ZONA"].str.upper().str.contains(q, na=False)
                | df_r["CANTON"].str.upper().str.contains(q, na=False)
                | df_r["CODIGO PAQUETES"].str.upper().str.contains(q, na=False)
            ]

        ra1, ra2, ra3 = st.columns([2, 1.4, 1.2])
        obs_rec_lote = ra1.text_input(
            "Novedad / Observación de retorno",
            placeholder="Ej: Retorno completo con actas y urnas",
            key="obs_rec_lote",
        )

        if ra2.button(
            f"📦 Marcar {len(df_r)} recinto(s) RECIBIDO EN BODEGA",
            type="primary",
            use_container_width=True,
            disabled=(len(df_r) == 0),
        ):
            ts = now_ec_str()
            recs = []
            for _, r in df_r.iterrows():
                recs.append(
                    {
                        "orden": int(r["ORDEN"]),
                        "entregado": 1,
                        "fecha_hora_entrega": r["FECHA_HORA_ENTREGA"],
                        "usuario_entrega": r["USUARIO_ENTREGA"],
                        "obs_entrega": r["OBS_ENTREGA"],
                        "recibido_bodega": 1,
                        "fecha_hora_finalizacion": r["FECHA Y HORA DE FINALIZACION"] if r["RECIBIDO_BODEGA"] and r["FECHA Y HORA DE FINALIZACION"] else ts,
                        "usuario_recepcion": operador,
                        "obs_recepcion": obs_rec_lote if obs_rec_lote else r["OBS_RECEPCION"],
                    }
                )
            upsert_status_records(recs)
            st.success(f"Registrados {len(recs)} recintos como RECIBIDO EN BODEGA ({ts}).")
            st.rerun()

        if ra3.button("↩️ Desmarcar Retorno", use_container_width=True, disabled=(len(df_r) == 0)):
            recs = []
            for _, r in df_r.iterrows():
                recs.append(
                    {
                        "orden": int(r["ORDEN"]),
                        "entregado": 1,
                        "fecha_hora_entrega": r["FECHA_HORA_ENTREGA"],
                        "usuario_entrega": r["USUARIO_ENTREGA"],
                        "obs_entrega": r["OBS_ENTREGA"],
                        "recibido_bodega": 0,
                        "fecha_hora_finalizacion": "",
                        "usuario_recepcion": "",
                        "obs_recepcion": "",
                    }
                )
            upsert_status_records(recs)
            st.warning(f"Se desmarcó el retorno en {len(recs)} recintos.")
            st.rerun()

        rec_cols = [
            "ORDEN", "RECIBIDO_BODEGA", "FECHA Y HORA DE FINALIZACION", "OBS_RECEPCION",
            "FECHA_HORA_ENTREGA", "FUERZA", "GT", "CAMION",
            "CANTON", "ZONA", "RECINTO", "NUMERO DE PAQUETES",
            "CODIGO PAQUETES", "CODIGO KIT CDA", "PERCHA", "NIVEL (POR PERCHA)",
        ]
        edited_rec = st.data_editor(
            df_r[rec_cols],
            use_container_width=True,
            hide_index=True,
            height=420,
            disabled=[c for c in rec_cols if c not in ("RECIBIDO_BODEGA", "OBS_RECEPCION")],
            column_config={
                "RECIBIDO_BODEGA": st.column_config.CheckboxColumn("RECIBIDO EN BODEGA", default=False),
                "OBS_RECEPCION": st.column_config.TextColumn("Observación Retorno"),
            },
            key="editor_recepcion",
        )
        if st.button("💾 Guardar cambios individuales de Retorno", type="primary", key="save_rec_ind"):
            ts = now_ec_str()
            orig_map = df_r.set_index("ORDEN").to_dict("index")
            to_save = []
            for _, row_ed in edited_rec.iterrows():
                o_id = int(row_ed["ORDEN"])
                o_prev = orig_map[o_id]
                new_rec = bool(row_ed["RECIBIDO_BODEGA"])
                new_obs = str(row_ed["OBS_RECEPCION"] or "")
                if new_rec != bool(o_prev["RECIBIDO_BODEGA"]) or new_obs != str(o_prev["OBS_RECEPCION"]):
                    to_save.append(
                        {
                            "orden": o_id,
                            "entregado": 1,
                            "fecha_hora_entrega": o_prev["FECHA_HORA_ENTREGA"],
                            "usuario_entrega": o_prev["USUARIO_ENTREGA"],
                            "obs_entrega": o_prev["OBS_ENTREGA"],
                            "recibido_bodega": int(new_rec),
                            "fecha_hora_finalizacion": (o_prev["FECHA Y HORA DE FINALIZACION"] or ts) if new_rec else "",
                            "usuario_recepcion": operador if new_rec else "",
                            "obs_recepcion": new_obs if new_rec else "",
                        }
                    )
            if to_save:
                upsert_status_records(to_save)
                st.success(f"Guardados {len(to_save)} cambios de retorno a bodega.")
                st.rerun()
            else:
                st.info("No se detectaron cambios pendientes.")
