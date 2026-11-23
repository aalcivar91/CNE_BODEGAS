import html
import re
import unicodedata
import pandas as pd
import streamlit as st
from utils import (
    ADMIN_PASSWORD,
    now_ec_str,
    render_alerta_reubicaciones,
    sort_camiones,
    upsert_status_records,
)

OPERADOR_DEFAULT = "Bodega Base Naval Sur"


def _norm_text(s: str) -> str:
    s = str(s).upper().strip()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _match_cod_paquete(cod_str: str, q_raw: str) -> bool:
    nums = [int(x) for x in re.findall(r"\d+", str(cod_str))]
    if not nums:
        return False
    start = nums[0]
    end = nums[-1] if len(nums) >= 2 else nums[0]
    q_num = int(q_raw)
    if start <= q_num <= end:
        return True
    if len(q_raw) <= 5 and (end - start) <= 500:
        return any(str(n).endswith(q_raw) for n in range(start, end + 1))
    return False


def _filtrar_busqueda(df_in: pd.DataFrame, busq: str) -> pd.DataFrame:
    if not busq.strip():
        return df_in
    q_raw = busq.strip()
    q = _norm_text(q_raw)
    mask = (
        df_in["RECINTO"].apply(_norm_text).str.contains(q, na=False, regex=False)
        | df_in["REUBICACION"].apply(_norm_text).str.contains(q, na=False, regex=False)
        | df_in["ZONA"].apply(_norm_text).str.contains(q, na=False, regex=False)
        | df_in["CANTON"].apply(_norm_text).str.contains(q, na=False, regex=False)
        | df_in["PARROQUIA"].apply(_norm_text).str.contains(q, na=False, regex=False)
        | df_in["CODIGO PAQUETES"].apply(_norm_text).str.contains(q, na=False, regex=False)
        | df_in["CODIGO KIT CDA"].apply(_norm_text).str.contains(q, na=False, regex=False)
    )
    if q_raw.isdigit():
        mask = mask | df_in["CODIGO PAQUETES"].apply(lambda x: _match_cod_paquete(x, q_raw))
    return df_in[mask]


def _filtrar_por_ordenes(df_in: pd.DataFrame, texto_ordenes: str) -> pd.DataFrame:
    if not texto_ordenes.strip():
        return df_in
    ids = set()
    for token in re.split(r"[\s,;]+", texto_ordenes.strip()):
        if not token:
            continue
        if "-" in token:
            partes = token.split("-", 1)
            if partes[0].isdigit() and partes[1].isdigit():
                a, b = int(partes[0]), int(partes[1])
                ids.update(range(min(a, b), max(a, b) + 1))
        elif token.isdigit():
            ids.add(int(token))
    return df_in[df_in["ORDEN"].isin(ids)] if ids else df_in


def _parse_nivel_por_percha(nivel_str: str) -> list[dict]:
    items = []
    if not nivel_str or str(nivel_str).strip().lower() == "nan":
        return items
    for raw_line in str(nivel_str).split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(";") if p.strip()]
        if not parts:
            continue
        percha = parts[0]
        rest = parts[1:]
        a_slots, b_slots = set(), set()
        a_lbls, b_lbls = [], []
        cant_match = re.search(r"\((\d+)\)", line)
        cant = f"{cant_match.group(1)} paq." if cant_match else ""

        for seg in rest:
            seg_clean = re.sub(r"\(\d+\)", "", seg).strip()
            for m in re.finditer(r"\b([AB])(\d+)(?:\s*-\s*[AB]?(\d+))?\b", seg_clean):
                lvl = m.group(1)
                n1 = int(m.group(2))
                n2 = int(m.group(3)) if m.group(3) else n1
                rng = set(range(min(n1, n2), max(n1, n2) + 1))
                lbl = f"{lvl}{n1}-{lvl}{n2}" if n2 != n1 else f"{lvl}{n1}"
                if lvl == "A":
                    a_slots.update(rng)
                    a_lbls.append(lbl)
                else:
                    b_slots.update(rng)
                    b_lbls.append(lbl)

        items.append(
            {
                "percha": percha,
                "a_slots": a_slots,
                "b_slots": b_slots,
                "a_lbl": ", ".join(a_lbls),
                "b_lbl": ", ".join(b_lbls),
                "cant": cant,
            }
        )
    return items


def _collect_perchas(df_sub: pd.DataFrame) -> list[str]:
    seen = []
    for val in df_sub["PERCHA"].tolist():
        for p in str(val).split(";"):
            p_clean = p.strip()
            if p_clean and p_clean not in seen:
                seen.append(p_clean)
    return seen


def _build_rack_bar(lvl: str, active_slots: set[int]) -> str:
    color_on = "#0284C7" if lvl == "A" else "#059669"
    border_on = "#38BDF8" if lvl == "A" else "#34D399"
    cells = []
    for i in range(1, 16):
        if i in active_slots:
            style = (
                f"background:{color_on};color:#FFFFFF;border:1px solid {border_on};"
                "font-weight:700;"
            )
        else:
            style = "background:#0F172A;color:#475569;border:1px solid #1E293B;font-weight:400;"
        cells.append(
            f'<span style="display:inline-block;width:22px;text-align:center;'
            f'font-size:0.70rem;padding:2px 0;border-radius:4px;margin:1px;{style}">{i}</span>'
        )
    lvl_badge_bg = "#0369A1" if lvl == "A" else "#047857"
    return (
        f'<div style="display:flex;align-items:center;gap:4px;margin-top:3px;flex-wrap:wrap;">'
        f'<span style="background:{lvl_badge_bg};color:#FFF;font-size:0.70rem;font-weight:700;'
        f'padding:2px 6px;border-radius:4px;min-width:52px;text-align:center;">NIVEL {lvl}</span>'
        f'{"".join(cells)}</div>'
    )


def _render_resumen_y_picking(df_view: pd.DataFrame, titulo_ctx: str = "selección actual"):
    if len(df_view) == 0:
        return

    cantones_list = list(dict.fromkeys([x for x in df_view["CANTON"].tolist() if x]))
    camiones_list = sort_camiones([x for x in df_view["CAMION"].unique().tolist() if x and x != "Sin asignar"])
    if "Sin asignar" in df_view["CAMION"].unique().tolist():
        camiones_list.append("Sin asignar")
    perchas_list = _collect_perchas(df_view)

    cantones_str = ", ".join(cantones_list[:12]) + (f" (+{len(cantones_list)-12} más)" if len(cantones_list) > 12 else "")
    camiones_str = ", ".join(camiones_list[:25]) + (f" (+{len(camiones_list)-25} más)" if len(camiones_list) > 25 else "")
    perchas_str = " · ".join(perchas_list[:14]) + (f" (+{len(perchas_list)-14} más)" if len(perchas_list) > 14 else "")

    st.markdown(
        f"""
        <div class="resumen-filtro-box">
            <strong>🏛️ Cantones ({len(cantones_list)}):</strong> {html.escape(cantones_str)}<br>
            <strong>🚚 Camiones ({len(camiones_list)}):</strong> {html.escape(camiones_str)}<br>
            <strong>🗄️ Perchas ({len(perchas_list)}):</strong> {html.escape(perchas_str) if perchas_str else "—"}<br>
            <strong>🏫 Recintos:</strong> {len(df_view):,} recintos en {html.escape(titulo_ctx)}.
        </div>
        """,
        unsafe_allow_html=True,
    )

    k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
    kpis = [
        (k1, f"{len(df_view):,}", "Recintos"),
        (k2, f"{int(df_view['NUMERO DE PAQUETES'].sum()):,}", "Paquetes / Kits"),
        (k3, f"{int(df_view['BIOMBOS'].sum()):,}", "Biombos"),
        (k4, f"{int(df_view['BIOMBO MAP'].sum()):,}", "Biombo MAP"),
        (k5, f"{int(df_view['URNAS BLANCAS'].sum()):,}", "Urnas Blancas"),
        (k6, f"{int(df_view['URNAS CAFÉS'].sum()):,}", "Urnas Cafés"),
        (k7, f"{int(df_view['KITS CDA'].sum()):,}", "Kits CDA"),
    ]
    for col_k, val, lbl in kpis:
        col_k.markdown(
            f'<div class="kpi-card"><div class="kpi-val">{val}</div><div class="kpi-lbl">{lbl}</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")

    # Guía visual de bodega (Percha, Nivel A/B y Códigos a sacar)
    auto_expand = len(df_view) <= 15
    with st.expander(
        f"🗄️ Guía Visual de Bodega — Percha, Nivel (A / B) y Códigos a sacar ({len(df_view)} recinto(s))",
        expanded=auto_expand,
    ):
        if len(df_view) > 25:
            st.info(
                f"Hay **{len(df_view)}** recintos en pantalla. Filtre por **Camión, Cantón, Parroquia, Recinto, Código** "
                "o **marque las casillas** en la tabla para visualizar el mapa detallado de perchas y niveles sin saturar la pantalla."
            )
            return

        cards_html = []
        for _, r in df_view.iterrows():
            ord_n = int(r["ORDEN"])
            recinto = html.escape(str(r["RECINTO"]))
            canton = html.escape(str(r["CANTON"]))
            parr = html.escape(str(r["PARROQUIA"]))
            zona = html.escape(str(r["ZONA"]))
            cam = html.escape(str(r["CAMION"]))
            gt_txt = f" · {html.escape(str(r['GT']))}" if str(r["GT"]).strip() else ""
            paq_n = int(r["NUMERO DE PAQUETES"])
            cod_paq = html.escape(str(r["CODIGO PAQUETES"]))
            cod_cda = html.escape(str(r["CODIGO KIT CDA"])) if str(r["CODIGO KIT CDA"]).strip() else "Sin Kit CDA"
            kits_cda = int(r["KITS CDA"])
            biombos = int(r["BIOMBOS"])
            b_map = int(r["BIOMBO MAP"])
            urnas_b = int(r["URNAS BLANCAS"])
            urnas_c = int(r["URNAS CAFÉS"])
            estado = html.escape(str(r["ESTADO"]))
            alerta = str(r.get("ALERTA_REUBICACION", "")).strip()

            shelves = _parse_nivel_por_percha(r["NIVEL (POR PERCHA)"])
            shelves_blocks = []
            for sh in shelves:
                p_name = html.escape(sh["percha"])
                is_der = "DERECHO" in sh["percha"].upper()
                p_bg = "#1D4ED8" if is_der else "#0F766E"
                p_border = "#60A5FA" if is_der else "#2DD4BF"

                badges = []
                if sh["a_lbl"]:
                    badges.append(
                        f'<span style="background:#0369A1;color:#E0F2FE;padding:2px 8px;border-radius:999px;'
                        f'font-size:0.78rem;font-weight:700;">Nivel A: {html.escape(sh["a_lbl"])}</span>'
                    )
                if sh["b_lbl"]:
                    badges.append(
                        f'<span style="background:#047857;color:#D1FAE5;padding:2px 8px;border-radius:999px;'
                        f'font-size:0.78rem;font-weight:700;">Nivel B: {html.escape(sh["b_lbl"])}</span>'
                    )
                if sh["cant"]:
                    badges.append(
                        f'<span style="background:#334155;color:#F8FAFC;padding:2px 8px;border-radius:999px;'
                        f'font-size:0.75rem;">{html.escape(sh["cant"])}</span>'
                    )

                rack_a = _build_rack_bar("A", sh["a_slots"]) if sh["a_slots"] else ""
                rack_b = _build_rack_bar("B", sh["b_slots"]) if sh["b_slots"] else ""

                shelves_blocks.append(
                    f'<div style="background:#0B1220;border:1px solid #334155;border-left:4px solid {p_border};'
                    f'border-radius:8px;padding:8px 10px;margin-top:6px;">'
                    f'  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px;">'
                    f'    <span style="background:{p_bg};color:#FFF;padding:3px 10px;border-radius:6px;'
                    f'font-size:0.84rem;font-weight:700;">🗄️ PERCHA {p_name}</span>'
                    f'    {"".join(badges)}'
                    f'  </div>'
                    f'  {rack_a}{rack_b}'
                    f'</div>'
                )

            alerta_html = ""
            if alerta:
                alerta_html = (
                    f'<div style="background:#450A0A;border:1px solid #DC2626;color:#FECACA;'
                    f'border-radius:6px;padding:6px 10px;margin-top:6px;font-size:0.82rem;font-weight:600;">'
                    f'{html.escape(alerta)}</div>'
                )

            cda_style = (
                "background:#4C1D95;color:#EDE9FE;border:1px solid #8B5CF6;"
                if kits_cda > 0
                else "background:#1E293B;color:#94A3B8;border:1px solid #334155;"
            )

            cards_html.append(
                f'<div style="background:#1E293B;border:1px solid #334155;border-radius:10px;'
                f'padding:10px 13px;margin-bottom:10px;color:#F8FAFC;">'
                f'  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;">'
                f'    <div style="font-size:0.95rem;font-weight:700;color:#F8FAFC;">'
                f'      <span style="background:#38BDF8;color:#0F172A;padding:2px 7px;border-radius:5px;margin-right:6px;">#{ord_n}</span>'
                f'      {recinto}'
                f'    </div>'
                f'    <div style="font-size:0.78rem;color:#CBD5E1;">'
                f'      {canton} / {parr}{(" / " + zona) if zona else ""} · <strong>Camión {cam}</strong>{gt_txt} · {estado}'
                f'    </div>'
                f'  </div>'
                f'  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:7px;align-items:center;">'
                f'    <span style="background:#78350F;color:#FEF3C7;border:1px solid #F59E0B;padding:3px 10px;'
                f'border-radius:6px;font-size:0.84rem;font-weight:700;">📦 Paquetes ({paq_n}): {cod_paq}</span>'
                f'    <span style="{cda_style}padding:3px 10px;border-radius:6px;font-size:0.82rem;font-weight:600;">'
                f'🧰 Kit CDA ({kits_cda}): {cod_cda}</span>'
                f'    <span style="background:#0F172A;color:#CBD5E1;border:1px solid #334155;padding:3px 9px;'
                f'border-radius:6px;font-size:0.78rem;">Biombos: <strong>{biombos}</strong> · MAP: <strong>{b_map}</strong> · '
                f'Urnas B/C: <strong>{urnas_b}/{urnas_c}</strong></span>'
                f'  </div>'
                f'  {alerta_html}'
                f'  {"".join(shelves_blocks)}'
                f'</div>'
            )

        st.markdown("".join(cards_html), unsafe_allow_html=True)


def _reset_ent_filtros():
    st.session_state["e_fz"] = "TODAS"
    st.session_state["e_gt"] = "TODOS"
    st.session_state["e_cam"] = "TODOS"
    st.session_state["e_est"] = "TODOS"
    st.session_state["e_can"] = "TODOS"
    st.session_state["e_par"] = "TODAS"
    st.session_state["e_zon"] = "TODAS"
    st.session_state["e_busq_recinto"] = ""
    st.session_state["e_ordenes_sel"] = ""


def _on_e_fz_change():
    st.session_state["e_gt"] = "TODOS"
    st.session_state["e_cam"] = "TODOS"
    st.session_state["e_can"] = "TODOS"
    st.session_state["e_par"] = "TODAS"
    st.session_state["e_zon"] = "TODAS"
    st.session_state["e_busq_recinto"] = ""
    st.session_state["e_ordenes_sel"] = ""


def _on_e_can_change():
    st.session_state["e_par"] = "TODAS"
    st.session_state["e_zon"] = "TODAS"


def _on_e_par_change():
    st.session_state["e_zon"] = "TODAS"


def _reset_rec_filtros():
    st.session_state["r_fz"] = "TODAS"
    st.session_state["r_gt"] = "TODOS"
    st.session_state["r_cam"] = "TODOS"
    st.session_state["r_est"] = "TODOS"
    st.session_state["r_can"] = "TODOS"
    st.session_state["r_par"] = "TODAS"
    st.session_state["r_zon"] = "TODAS"
    st.session_state["r_busq_recinto"] = ""
    st.session_state["r_ordenes_sel"] = ""


def _on_r_fz_change():
    st.session_state["r_gt"] = "TODOS"
    st.session_state["r_cam"] = "TODOS"
    st.session_state["r_can"] = "TODOS"
    st.session_state["r_par"] = "TODAS"
    st.session_state["r_zon"] = "TODAS"
    st.session_state["r_busq_recinto"] = ""
    st.session_state["r_ordenes_sel"] = ""


def _on_r_can_change():
    st.session_state["r_par"] = "TODAS"
    st.session_state["r_zon"] = "TODAS"


def _on_r_par_change():
    st.session_state["r_zon"] = "TODAS"


def render(df_all: pd.DataFrame):
    if "auth_ok" not in st.session_state:
        st.session_state["auth_ok"] = False

    if not st.session_state["auth_ok"]:
        st.subheader("Control Operativo de Bodega — Despacho y Retorno")
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

    top_a, top_b = st.columns([5, 1.2])
    top_a.subheader("Control Operativo de Bodega — Despacho y Retorno")
    with top_b:
        st.write("")
        if st.button("🔒 Cerrar sesión", use_container_width=True):
            st.session_state["auth_ok"] = False
            st.rerun()

    operador = OPERADOR_DEFAULT

    modo_ctrl = st.radio(
        "Etapa operativa:",
        [
            "🚚 Despacho desde Bodega a Jefes De Recinto",
            "📦 Recibido en Bodega — Post-Elecciones",
        ],
        horizontal=True,
        key="ctrl_modo",
    )

    # ==========================================================================
    # MODO A: DESPACHO DESDE BODEGA (ENTREGADO)
    # ==========================================================================
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

        fg1, fg2, fg3 = st.columns(3)
        e_can_opts = ["TODOS"] + sorted([x for x in df_e["CANTON"].unique().tolist() if x])
        if st.session_state.get("e_can", "TODOS") not in e_can_opts:
            st.session_state["e_can"] = "TODOS"
        e_can = fg1.selectbox("Cantón", e_can_opts, key="e_can", on_change=_on_e_can_change)
        if e_can != "TODOS":
            df_e = df_e[df_e["CANTON"] == e_can]

        e_par_opts = ["TODAS"] + sorted([x for x in df_e["PARROQUIA"].unique().tolist() if x])
        if st.session_state.get("e_par", "TODAS") not in e_par_opts:
            st.session_state["e_par"] = "TODAS"
        e_par = fg2.selectbox("Parroquia", e_par_opts, key="e_par", on_change=_on_e_par_change)
        if e_par != "TODAS":
            df_e = df_e[df_e["PARROQUIA"] == e_par]

        e_zon_opts = ["TODAS"] + sorted([x for x in df_e["ZONA"].unique().tolist() if x])
        if st.session_state.get("e_zon", "TODAS") not in e_zon_opts:
            st.session_state["e_zon"] = "TODAS"
        e_zon = fg3.selectbox("Zona", e_zon_opts, key="e_zon")
        if e_zon != "TODAS":
            df_e = df_e[df_e["ZONA"] == e_zon]

        b1, b2 = st.columns([2, 1.2])
        e_busq = b1.text_input(
            "🔎 Buscar por nombre de Recinto, Zona, Parroquia o Código de Paquete",
            placeholder="Ej: 377, 900378, MILAGRO, 9 DE OCTUBRE...",
            key="e_busq_recinto",
        )
        e_ordenes = b2.text_input(
            "🎯 Filtrar por N° de ORDEN (varios)",
            placeholder="Ej: 2 4 66 77",
            key="e_ordenes_sel",
        )
        df_e = _filtrar_busqueda(df_e, e_busq)
        df_e = _filtrar_por_ordenes(df_e, e_ordenes)

        render_alerta_reubicaciones(df_e)

        # Contenedores superiores (se rellenan tras leer casillas marcadas en la tabla)
        panel_resumen_e = st.container()
        barra_accion_e = st.container()

        st.markdown("##### 📋 Selección individual por recinto (marque las casillas y pulse el botón superior)")
        edit_cols = [
            "ORDEN", "ENTREGADO", "FECHA_HORA_ENTREGA", "OBS_ENTREGA",
            "DIA_ENTREGA", "HORA_STR", "FUERZA", "GT", "CAMION",
            "CANTON", "PARROQUIA", "ZONA", "RECINTO", "ALERTA_REUBICACION",
            "NUMERO DE PAQUETES", "CODIGO PAQUETES", "CODIGO KIT CDA", "PERCHA", "NIVEL (POR PERCHA)",
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
                "ALERTA_REUBICACION": st.column_config.TextColumn("⚠️ Alerta Reubicación", width="large"),
            },
            key="editor_entregas",
        )

        orig_map = df_e.set_index("ORDEN").to_dict("index")
        nuevos_ent = []
        nuevos_pend = []
        solo_obs = []
        for _, row_ed in edited_ent.iterrows():
            o_id = int(row_ed["ORDEN"])
            o_prev = orig_map[o_id]
            new_ent = bool(row_ed["ENTREGADO"])
            old_ent = bool(o_prev["ENTREGADO"])
            new_obs = str(row_ed["OBS_ENTREGA"] or "")
            old_obs = str(o_prev["OBS_ENTREGA"] or "")
            if new_ent and not old_ent:
                nuevos_ent.append((o_id, new_obs))
            elif not new_ent and old_ent:
                nuevos_pend.append(o_id)
            elif new_obs != old_obs:
                solo_obs.append((o_id, new_ent, new_obs))

        hay_filtro_e = len(df_e) < len(df_all)

        # Resumen KPI + Guía Visual de Bodega (responde en vivo a casillas marcadas o filtro)
        with panel_resumen_e:
            if len(nuevos_ent) > 0:
                ids_marcados = [x[0] for x in nuevos_ent]
                df_pick_e = df_e[df_e["ORDEN"].isin(ids_marcados)]
                _render_resumen_y_picking(df_pick_e, titulo_ctx="las casillas marcadas")
            else:
                _render_resumen_y_picking(df_e, titulo_ctx="la selección actual")

        with barra_accion_e:
            st.markdown("##### ⚡ Acción sobre selección actual")
            if len(nuevos_ent) > 0:
                ids_marcados = [x[0] for x in nuevos_ent]
                render_alerta_reubicaciones(df_e[df_e["ORDEN"].isin(ids_marcados)], solo_si_exacto=False)

            qa1, qa2, qa3 = st.columns([2, 1.5, 1.2])
            obs_lote = qa1.text_input(
                "Observación de despacho (opcional)",
                placeholder="Ej: Acta firmada sin novedad",
                key="obs_ent_lote",
            )

            if len(nuevos_ent) > 0:
                ords_txt = ", ".join(str(x[0]) for x in nuevos_ent[:8]) + ("..." if len(nuevos_ent) > 8 else "")
                btn_lbl = f"✅ Marcar {len(nuevos_ent)} seleccionado(s) como ENTREGADO (Orden: {ords_txt})"
                btn_disabled = False
            elif len(solo_obs) > 0:
                btn_lbl = f"💾 Guardar {len(solo_obs)} observación(es) modificada(s)"
                btn_disabled = False
            elif hay_filtro_e and len(df_e) > 0:
                btn_lbl = f"✅ Marcar {len(df_e)} filtrado(s) como ENTREGADO"
                btn_disabled = False
            else:
                btn_lbl = "Marque recintos en la tabla o filtre un camión"
                btn_disabled = True

            if qa2.button(btn_lbl, type="primary", use_container_width=True, disabled=btn_disabled, key="btn_ent_dyn"):
                ts = now_ec_str()
                recs = []
                if len(nuevos_ent) > 0 or len(solo_obs) > 0:
                    for o_id, row_obs in nuevos_ent:
                        o_prev = orig_map[o_id]
                        recs.append(
                            {
                                "orden": o_id,
                                "entregado": 1,
                                "fecha_hora_entrega": ts,
                                "usuario_entrega": operador,
                                "obs_entrega": obs_lote if obs_lote else row_obs,
                                "recibido_bodega": int(bool(o_prev["RECIBIDO_BODEGA"])),
                                "fecha_hora_finalizacion": o_prev["FECHA Y HORA DE FINALIZACION"],
                                "usuario_recepcion": o_prev["USUARIO_RECEPCION"],
                                "obs_recepcion": o_prev["OBS_RECEPCION"],
                            }
                        )
                    for o_id, cur_ent, row_obs in solo_obs:
                        o_prev = orig_map[o_id]
                        recs.append(
                            {
                                "orden": o_id,
                                "entregado": int(cur_ent),
                                "fecha_hora_entrega": o_prev["FECHA_HORA_ENTREGA"],
                                "usuario_entrega": operador if cur_ent else "",
                                "obs_entrega": row_obs,
                                "recibido_bodega": int(bool(o_prev["RECIBIDO_BODEGA"])),
                                "fecha_hora_finalizacion": o_prev["FECHA Y HORA DE FINALIZACION"],
                                "usuario_recepcion": o_prev["USUARIO_RECEPCION"],
                                "obs_recepcion": o_prev["OBS_RECEPCION"],
                            }
                        )
                else:
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
                st.success(f"Registrados {len(recs)} recinto(s) como ENTREGADO ({ts}).")
                st.rerun()

            if len(nuevos_pend) > 0:
                rev_lbl = f"↩️ Revertir {len(nuevos_pend)} desmarcado(s) a PENDIENTE"
                rev_disabled = False
            elif hay_filtro_e and len(df_e) > 0:
                rev_lbl = f"↩️ Revertir {len(df_e)} filtrado(s) a PENDIENTE"
                rev_disabled = False
            else:
                rev_lbl = "↩️ Revertir a PENDIENTE"
                rev_disabled = True

            if qa3.button(rev_lbl, use_container_width=True, disabled=rev_disabled, key="btn_rev_dyn"):
                ids_rev = nuevos_pend if len(nuevos_pend) > 0 else [int(x) for x in df_e["ORDEN"].tolist()]
                recs = [
                    {
                        "orden": o_id,
                        "entregado": 0,
                        "fecha_hora_entrega": "",
                        "usuario_entrega": "",
                        "obs_entrega": "",
                        "recibido_bodega": 0,
                        "fecha_hora_finalizacion": "",
                        "usuario_recepcion": "",
                        "obs_recepcion": "",
                    }
                    for o_id in ids_rev
                ]
                upsert_status_records(recs)
                st.warning(f"Se revirtieron {len(recs)} recinto(s) a PENDIENTE.")
                st.rerun()

    # ==========================================================================
    # MODO B: RECIBIDO EN BODEGA (SOLO HABILITADO PARA RECINTOS YA ENTREGADOS)
    # ==========================================================================
    else:
        df_entregados = df_all[df_all["ENTREGADO"]].copy()
        if len(df_entregados) == 0:
            st.warning(
                "🔒 Todavía no hay recintos marcados como **ENTREGADO**. "
                "La recepción en bodega (domingo post-elecciones) se habilita automáticamente únicamente para los recintos que ya fueron entregados."
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

        rg1, rg2, rg3 = st.columns(3)
        r_can_opts = ["TODOS"] + sorted([x for x in df_r["CANTON"].unique().tolist() if x])
        if st.session_state.get("r_can", "TODOS") not in r_can_opts:
            st.session_state["r_can"] = "TODOS"
        r_can = rg1.selectbox("Cantón", r_can_opts, key="r_can", on_change=_on_r_can_change)
        if r_can != "TODOS":
            df_r = df_r[df_r["CANTON"] == r_can]

        r_par_opts = ["TODAS"] + sorted([x for x in df_r["PARROQUIA"].unique().tolist() if x])
        if st.session_state.get("r_par", "TODAS") not in r_par_opts:
            st.session_state["r_par"] = "TODAS"
        r_par = rg2.selectbox("Parroquia", r_par_opts, key="r_par", on_change=_on_r_par_change)
        if r_par != "TODAS":
            df_r = df_r[df_r["PARROQUIA"] == r_par]

        r_zon_opts = ["TODAS"] + sorted([x for x in df_r["ZONA"].unique().tolist() if x])
        if st.session_state.get("r_zon", "TODAS") not in r_zon_opts:
            st.session_state["r_zon"] = "TODAS"
        r_zon = rg3.selectbox("Zona", r_zon_opts, key="r_zon")
        if r_zon != "TODAS":
            df_r = df_r[df_r["ZONA"] == r_zon]

        rb1, rb2 = st.columns([2, 1.2])
        r_busq = rb1.text_input(
            "🔎 Buscar por nombre de Recinto, Zona, Parroquia o Código de Paquete",
            placeholder="Ej: 377, 900378, MILAGRO, 9 DE OCTUBRE...",
            key="r_busq_recinto",
        )
        r_ordenes = rb2.text_input(
            "🎯 Filtrar por N° de ORDEN (varios)",
            placeholder="Ej: 2 4 66 77",
            key="r_ordenes_sel",
        )
        df_r = _filtrar_busqueda(df_r, r_busq)
        df_r = _filtrar_por_ordenes(df_r, r_ordenes)

        render_alerta_reubicaciones(df_r)

        panel_resumen_r = st.container()
        barra_accion_r = st.container()

        st.markdown("##### 📋 Selección individual por recinto (Retorno a Bodega)")
        rec_cols = [
            "ORDEN", "RECIBIDO_BODEGA", "FECHA Y HORA DE FINALIZACION", "OBS_RECEPCION",
            "FECHA_HORA_ENTREGA", "FUERZA", "GT", "CAMION",
            "CANTON", "PARROQUIA", "ZONA", "RECINTO", "ALERTA_REUBICACION",
            "NUMERO DE PAQUETES", "CODIGO PAQUETES", "CODIGO KIT CDA", "PERCHA", "NIVEL (POR PERCHA)",
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
                "ALERTA_REUBICACION": st.column_config.TextColumn("⚠️ Alerta Reubicación", width="large"),
            },
            key="editor_recepcion",
        )

        orig_map_r = df_r.set_index("ORDEN").to_dict("index")
        nuevos_rec = []
        desm_rec = []
        solo_obs_r = []
        for _, row_ed in edited_rec.iterrows():
            o_id = int(row_ed["ORDEN"])
            o_prev = orig_map_r[o_id]
            new_r = bool(row_ed["RECIBIDO_BODEGA"])
            old_r = bool(o_prev["RECIBIDO_BODEGA"])
            new_obs = str(row_ed["OBS_RECEPCION"] or "")
            old_obs = str(o_prev["OBS_RECEPCION"] or "")
            if new_r and not old_r:
                nuevos_rec.append((o_id, new_obs))
            elif not new_r and old_r:
                desm_rec.append(o_id)
            elif new_obs != old_obs:
                solo_obs_r.append((o_id, new_r, new_obs))

        hay_filtro_r = len(df_r) < len(df_entregados)

        with panel_resumen_r:
            if len(nuevos_rec) > 0:
                ids_marcados_r = [x[0] for x in nuevos_rec]
                df_pick_r = df_r[df_r["ORDEN"].isin(ids_marcados_r)]
                _render_resumen_y_picking(df_pick_r, titulo_ctx="las casillas marcadas")
            else:
                _render_resumen_y_picking(df_r, titulo_ctx="la selección actual")

        with barra_accion_r:
            st.markdown("##### ⚡ Acción sobre selección actual")
            ra1, ra2, ra3 = st.columns([2, 1.5, 1.2])
            obs_rec_lote = ra1.text_input(
                "Novedad / Observación de retorno (opcional)",
                placeholder="Ej: Retorno completo con actas y urnas",
                key="obs_rec_lote",
            )

            if len(nuevos_rec) > 0:
                ords_txt = ", ".join(str(x[0]) for x in nuevos_rec[:8]) + ("..." if len(nuevos_rec) > 8 else "")
                r_btn_lbl = f"📦 Marcar {len(nuevos_rec)} seleccionado(s) RECIBIDO EN BODEGA (Orden: {ords_txt})"
                r_btn_dis = False
            elif len(solo_obs_r) > 0:
                r_btn_lbl = f"💾 Guardar {len(solo_obs_r)} observación(es) de retorno"
                r_btn_dis = False
            elif hay_filtro_r and len(df_r) > 0:
                r_btn_lbl = f"📦 Marcar {len(df_r)} filtrado(s) RECIBIDO EN BODEGA"
                r_btn_dis = False
            else:
                r_btn_lbl = "Marque recintos en la tabla o filtre un camión"
                r_btn_dis = True

            if ra2.button(r_btn_lbl, type="primary", use_container_width=True, disabled=r_btn_dis, key="btn_rec_dyn"):
                ts = now_ec_str()
                recs = []
                if len(nuevos_rec) > 0 or len(solo_obs_r) > 0:
                    for o_id, row_obs in nuevos_rec:
                        o_prev = orig_map_r[o_id]
                        recs.append(
                            {
                                "orden": o_id,
                                "entregado": 1,
                                "fecha_hora_entrega": o_prev["FECHA_HORA_ENTREGA"],
                                "usuario_entrega": o_prev["USUARIO_ENTREGA"],
                                "obs_entrega": o_prev["OBS_ENTREGA"],
                                "recibido_bodega": 1,
                                "fecha_hora_finalizacion": ts,
                                "usuario_recepcion": operador,
                                "obs_recepcion": obs_rec_lote if obs_rec_lote else row_obs,
                            }
                        )
                    for o_id, cur_r, row_obs in solo_obs_r:
                        o_prev = orig_map_r[o_id]
                        recs.append(
                            {
                                "orden": o_id,
                                "entregado": 1,
                                "fecha_hora_entrega": o_prev["FECHA_HORA_ENTREGA"],
                                "usuario_entrega": o_prev["USUARIO_ENTREGA"],
                                "obs_entrega": o_prev["OBS_ENTREGA"],
                                "recibido_bodega": int(cur_r),
                                "fecha_hora_finalizacion": o_prev["FECHA Y HORA DE FINALIZACION"],
                                "usuario_recepcion": operador if cur_r else "",
                                "obs_recepcion": row_obs,
                            }
                        )
                else:
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
                st.success(f"Registrados {len(recs)} recinto(s) como RECIBIDO EN BODEGA ({ts}).")
                st.rerun()

            if len(desm_rec) > 0:
                r_rev_lbl = f"↩️ Desmarcar {len(desm_rec)} retorno(s)"
                r_rev_dis = False
            elif hay_filtro_r and len(df_r) > 0:
                r_rev_lbl = f"↩️ Desmarcar {len(df_r)} filtrado(s)"
                r_rev_dis = False
            else:
                r_rev_lbl = "↩️ Desmarcar Retorno"
                r_rev_dis = True

            if ra3.button(r_rev_lbl, use_container_width=True, disabled=r_rev_dis, key="btn_rev_rec_dyn"):
                ids_rev = desm_rec if len(desm_rec) > 0 else [int(x) for x in df_r["ORDEN"].tolist()]
                recs = []
                for o_id in ids_rev:
                    o_prev = orig_map_r[o_id]
                    recs.append(
                        {
                            "orden": o_id,
                            "entregado": 1,
                            "fecha_hora_entrega": o_prev["FECHA_HORA_ENTREGA"],
                            "usuario_entrega": o_prev["USUARIO_ENTREGA"],
                            "obs_entrega": o_prev["OBS_ENTREGA"],
                            "recibido_bodega": 0,
                            "fecha_hora_finalizacion": "",
                            "usuario_recepcion": "",
                            "obs_recepcion": "",
                        }
                    )
                upsert_status_records(recs)
                st.warning(f"Se desmarcó el retorno en {len(recs)} recinto(s).")
                st.rerun()
