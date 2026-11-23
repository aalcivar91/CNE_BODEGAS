import io
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

TZ_EC = ZoneInfo("America/Guayaquil")
EXCEL_PATH = "Plan_Entrega_Material_Electoral_Ordenado-v25.xlsx"
SQLITE_PATH = "estado_despacho_guayas.db"

# Tasa operativa calibrada: 400 paquetes / hora (6.6667 paq/min)
RATE_PAQ_PER_MIN = 400.0 / 60.0

# Margen operativo por camión usado en el plan v25 (FINEX Vie 16:00 / Sáb 22:00)
BUFFER_MIN_BY_BLOCK = {
    "Bloque 0 - Puná": 55.05,
    "Bloque 1 - Ejército": 8.85,
    "Bloque 2 - FAE": 35.40,
    "Bloque 3 - Armada": 1.66,
}


def get_secret(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return os.environ.get(key, default)


ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "DINDES2026")
SUPABASE_URL = get_secret("SUPABASE_URL", "")
SUPABASE_KEY = get_secret("SUPABASE_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)


def inject_css():
    st.markdown(
        """
        <style>
        .main-banner {
            background: linear-gradient(135deg, #1B365D 0%, #2C4A70 100%);
            color: white;
            padding: 1.0rem 1.35rem;
            border-radius: 12px;
            margin-bottom: 0.85rem;
        }
        .main-banner h2 { margin: 0; font-size: 1.4rem; color: white !important; }
        .main-banner p { margin: 0.25rem 0 0 0; opacity: 0.92; font-size: 0.9rem; color: #E2E8F0 !important; }
        .franja-box {
            background: #F1F5F9;
            color: #0F172A !important;
            border-left: 5px solid #1B365D;
            padding: 0.85rem 1.1rem;
            border-radius: 8px;
            margin-bottom: 0.75rem;
            font-weight: 500;
            line-height: 1.55;
        }
        .franja-box strong { color: #1B365D !important; }
        .franja-delay {
            background: #FEF3C7;
            color: #78350F !important;
            border-left: 5px solid #D97706;
            padding: 0.85rem 1.1rem;
            border-radius: 8px;
            margin-bottom: 0.75rem;
            font-weight: 500;
            line-height: 1.55;
        }
        .franja-delay strong { color: #92400E !important; }
        .resumen-filtro-box {
            background: #1E293B;
            color: #F8FAFC !important;
            border: 1px solid #334155;
            border-left: 5px solid #38BDF8;
            padding: 0.75rem 1.05rem;
            border-radius: 8px;
            margin-bottom: 0.9rem;
            font-size: 0.9rem;
            line-height: 1.5;
        }
        .resumen-filtro-box strong { color: #7DD3FC !important; }
        .kpi-card {
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 10px;
            padding: 0.7rem 0.85rem;
            text-align: center;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        }
        .kpi-val { font-size: 1.3rem; font-weight: 700; color: #1B365D !important; }
        .kpi-lbl { font-size: 0.78rem; color: #475569 !important; margin-top: 2px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fmt_alerta_reub(val: str) -> str:
    v = str(val).strip()
    if not v or v.lower() == "nan":
        return ""
    if v.upper().startswith("REUBICACI"):
        return f"⚠️ {v}"
    return f"⚠️ Reubicación por mal estado de recinto, usted debe ir a {v}"


def render_alerta_reubicaciones(df_vista: pd.DataFrame, solo_si_exacto: bool = True):
    if "ALERTA_REUBICACION" not in df_vista.columns or len(df_vista) == 0:
        return
    df_al = df_vista[df_vista["ALERTA_REUBICACION"] != ""]
    if len(df_al) == 0:
        return
    # Si hay otros recintos no afectados en pantalla, no mostrar el banner
    if solo_si_exacto and len(df_al) != len(df_vista):
        return
    lineas = []
    for _, r in df_al.iterrows():
        kit_txt = f" · `{r['CODIGO KIT CDA']}`" if str(r.get("CODIGO KIT CDA", "")).strip() else ""
        lineas.append(
            f"- **Orden {int(r['ORDEN'])} — {r['RECINTO']}** ({r['CANTON']} | Paquetes `{r['CODIGO PAQUETES']}`{kit_txt}): "
            f"**{r['ALERTA_REUBICACION']}**"
        )
    st.error(
        "🌧️ **ALERTA DE REUBICACIÓN DE RECINTO:** "
        "Se retiran los **mismos paquetes y kits asignados**, pero el material debe trasladarse al nuevo recinto indicado:\n\n"
        + "\n".join(lineas)
    )


@st.cache_data(show_spinner=False)
def load_base_data(path: str = EXCEL_PATH) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Base de Datos")
    df = df[pd.to_numeric(df["ORDEN"], errors="coerce").notna()].copy().reset_index(drop=True)

    df["ORDEN"] = df["ORDEN"].astype(int)
    df["NUMERO DE PAQUETES"] = pd.to_numeric(df["NUMERO DE PAQUETES"], errors="coerce").fillna(0).astype(int)
    df["KITS CDA"] = pd.to_numeric(df["KITS CDA"], errors="coerce").fillna(0).astype(int)

    df["BIOMBOS"] = df["NUMERO DE PAQUETES"] * 2
    df["BIOMBO MAP"] = 2
    df["URNAS BLANCAS"] = df["NUMERO DE PAQUETES"]
    df["URNAS CAFÉS"] = df["NUMERO DE PAQUETES"]

    if "REUBICACION" not in df.columns:
        df["REUBICACION"] = ""

    for col in [
        "BLOQUE", "HORA BLOQUE", "CANTON", "PARROQUIA", "ZONA", "RECINTO",
        "CDA", "CODIGO KIT CDA", "CODIGO PAQUETES", "PERCHA",
        "NIVEL (POR PERCHA)", "FUERZA", "GT", "RESPONSABLE", "REUBICACION"
    ]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    def fmt_cam(v):
        if pd.isna(v) or str(v).strip() == "":
            return "Sin asignar"
        s = str(v).strip()
        return s[:-2] if s.endswith(".0") else s

    df["CAMION"] = df["CAMION"].apply(fmt_cam)

    df["FECHA_DT"] = pd.to_datetime(df["FECHA RETIRO"], errors="coerce")
    df["FECHA_STR"] = df["FECHA_DT"].dt.strftime("%d/%m/%Y").fillna("")
    df["DIA_ENTREGA"] = df["FECHA_DT"].dt.strftime("%Y-%m-%d").map(
        {
            "2026-11-27": "Viernes 27/11",
            "2026-11-28": "Sábado 28/11",
        }
    ).fillna("Por definir")

    def fmt_hora(v):
        if pd.isna(v) or str(v).strip() == "":
            return ""
        return str(v).strip()[:5]

    df["HORA_STR"] = df["HORA DE RETIRO"].apply(fmt_hora)
    df["ALERTA_REUBICACION"] = df["REUBICACION"].apply(_fmt_alerta_reub)
    return df


def init_sqlite():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS estado_logistico (
            orden INTEGER PRIMARY KEY,
            entregado INTEGER DEFAULT 0,
            fecha_hora_entrega TEXT DEFAULT '',
            usuario_entrega TEXT DEFAULT '',
            obs_entrega TEXT DEFAULT '',
            recibido_bodega INTEGER DEFAULT 0,
            fecha_hora_finalizacion TEXT DEFAULT '',
            usuario_recepcion TEXT DEFAULT '',
            obs_recepcion TEXT DEFAULT ''
        )
        """
    )
    conn.commit()
    conn.close()


@st.cache_resource
def get_supabase_client():
    if not USE_SUPABASE:
        return None
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


@st.cache_data(ttl=20, show_spinner=False)
def load_status_df() -> pd.DataFrame:
    cols = [
        "orden", "entregado", "fecha_hora_entrega", "usuario_entrega", "obs_entrega",
        "recibido_bodega", "fecha_hora_finalizacion", "usuario_recepcion", "obs_recepcion",
    ]
    if USE_SUPABASE:
        sb = get_supabase_client()
        resp = sb.table("estado_logistico").select("*").limit(2000).execute()
        data = resp.data or []
        if not data:
            return pd.DataFrame(columns=cols)
        df_st = pd.DataFrame(data)
        for c in cols:
            if c not in df_st.columns:
                df_st[c] = "" if "fecha" in c or "obs" in c or "usuario" in c else 0
        return df_st[cols]
    else:
        init_sqlite()
        conn = sqlite3.connect(SQLITE_PATH)
        df_st = pd.read_sql_query("SELECT * FROM estado_logistico", conn)
        conn.close()
        return df_st


def upsert_status_records(records: list[dict]):
    if not records:
        return
    if USE_SUPABASE:
        sb = get_supabase_client()
        sb.table("estado_logistico").upsert(records, on_conflict="orden").execute()
    else:
        init_sqlite()
        conn = sqlite3.connect(SQLITE_PATH)
        cur = conn.cursor()
        for r in records:
            cur.execute(
                """
                INSERT INTO estado_logistico (
                    orden, entregado, fecha_hora_entrega, usuario_entrega, obs_entrega,
                    recibido_bodega, fecha_hora_finalizacion, usuario_recepcion, obs_recepcion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(orden) DO UPDATE SET
                    entregado=excluded.entregado,
                    fecha_hora_entrega=excluded.fecha_hora_entrega,
                    usuario_entrega=excluded.usuario_entrega,
                    obs_entrega=excluded.obs_entrega,
                    recibido_bodega=excluded.recibido_bodega,
                    fecha_hora_finalizacion=excluded.fecha_hora_finalizacion,
                    usuario_recepcion=excluded.usuario_recepcion,
                    obs_recepcion=excluded.obs_recepcion
                """,
                (
                    int(r["orden"]),
                    int(bool(r["entregado"])),
                    str(r.get("fecha_hora_entrega", "")),
                    str(r.get("usuario_entrega", "")),
                    str(r.get("obs_entrega", "")),
                    int(bool(r["recibido_bodega"])),
                    str(r.get("fecha_hora_finalizacion", "")),
                    str(r.get("usuario_recepcion", "")),
                    str(r.get("obs_recepcion", "")),
                ),
            )
        conn.commit()
        conn.close()
    load_status_df.clear()


def apply_dynamic_eta(df_in: pd.DataFrame, now_dt: datetime | None = None) -> pd.DataFrame:
    """
    Recalcula en tiempo real HORA_ESTIMADA, DESFASE_MIN y ESTADO_HORARIO
    a tasa de 400 paquetes/hora, propagando demoras reales y del reloj actual.
    """
    if now_dt is None:
        now_dt = datetime.now(TZ_EC)

    df_out = df_in.copy()
    df_out["HORA_ESTIMADA"] = df_out["HORA_STR"]
    df_out["DESFASE_MIN"] = 0
    df_out["ESTADO_HORARIO"] = "🟢 A tiempo"

    valid_dates = df_out["FECHA_DT"].notna()
    for day_val, g_day in df_out[valid_dates].groupby(df_out.loc[valid_dates, "FECHA_DT"].dt.date, sort=True):
        idxs = g_day.index.tolist()
        if not idxs:
            continue

        groups = []
        s_i = 0

        def gkey(idx):
            r = df_out.loc[idx]
            return (r["BLOQUE"], r["FUERZA"], r["GT"], r["CAMION"])

        cur_k = gkey(idxs[0])
        for pos in range(1, len(idxs)):
            k = gkey(idxs[pos])
            if k != cur_k:
                groups.append((cur_k, idxs[s_i:pos]))
                cur_k = k
                s_i = pos
        groups.append((cur_k, idxs[s_i:]))

        plan_starts = []
        plan_ends = []
        for (blk, fz, gt, cam), g_idxs in groups:
            h_s = df_out.loc[g_idxs[0], "HORA_STR"]
            try:
                hh, mm = map(int, h_s.split(":"))
            except Exception:
                hh, mm = 0, 0
            t_start = datetime(day_val.year, day_val.month, day_val.day, hh, mm, tzinfo=TZ_EC)
            paq = int(df_out.loc[g_idxs, "NUMERO DE PAQUETES"].sum())
            dur = (paq / RATE_PAQ_PER_MIN) + BUFFER_MIN_BY_BLOCK.get(blk, 5.0)
            plan_starts.append(t_start)
            plan_ends.append(t_start + timedelta(minutes=dur))

        for idx_g in range(len(groups) - 1):
            if groups[idx_g][0][0] in ("Bloque 0 - Puná", "Bloque 2 - FAE"):
                plan_ends[idx_g] = plan_starts[idx_g + 1]

        current_delay = 0
        is_same_day = (now_dt.date() == day_val)

        for idx_g, ((blk, fz, gt, cam), g_idxs) in enumerate(groups):
            t_prog_start = plan_starts[idx_g]
            t_prog_end = plan_ends[idx_g]
            all_done = bool(df_out.loc[g_idxs, "ENTREGADO"].all())

            if all_done:
                real_times = []
                for ts_s in df_out.loc[g_idxs, "FECHA_HORA_ENTREGA"]:
                    try:
                        real_times.append(
                            datetime.strptime(str(ts_s).strip(), "%d/%m/%Y %H:%M").replace(tzinfo=TZ_EC)
                        )
                    except Exception:
                        pass
                if real_times:
                    t_real_end = max(real_times)
                    if t_real_end.date() == day_val:
                        current_delay = max(0, int(round((t_real_end - t_prog_end).total_seconds() / 60.0)))
                    df_out.loc[g_idxs, "HORA_ESTIMADA"] = t_real_end.strftime("%H:%M")
                else:
                    df_out.loc[g_idxs, "HORA_ESTIMADA"] = df_out.loc[g_idxs, "HORA_STR"]

                df_out.loc[g_idxs, "DESFASE_MIN"] = 0
                df_out.loc[g_idxs, "ESTADO_HORARIO"] = "✅ Entregado"
            else:
                t_est_start = t_prog_start + timedelta(minutes=current_delay)
                t_est_end = t_prog_end + timedelta(minutes=current_delay)

                df_out.loc[g_idxs, "HORA_ESTIMADA"] = t_est_start.strftime("%H:%M")
                df_out.loc[g_idxs, "DESFASE_MIN"] = current_delay

                if is_same_day and now_dt > t_est_end:
                    over_min = int(round((now_dt - t_est_end).total_seconds() / 60.0))
                    total_over = current_delay + over_min
                    df_out.loc[g_idxs, "ESTADO_HORARIO"] = f"🔴 En curso / Demora +{total_over} min"
                    current_delay += over_min
                elif current_delay > 0:
                    df_out.loc[g_idxs, "ESTADO_HORARIO"] = f"🟡 Reprogramado +{current_delay} min"
                else:
                    df_out.loc[g_idxs, "ESTADO_HORARIO"] = "🟢 A tiempo"

    return df_out


def get_merged_df(now_dt: datetime | None = None) -> pd.DataFrame:
    base = load_base_data(EXCEL_PATH).copy()
    st_df = load_status_df()
    if len(st_df) == 0:
        base["ENTREGADO"] = False
        base["FECHA_HORA_ENTREGA"] = ""
        base["USUARIO_ENTREGA"] = ""
        base["OBS_ENTREGA"] = ""
        base["RECIBIDO_BODEGA"] = False
        base["FECHA Y HORA DE FINALIZACION"] = ""
        base["USUARIO_RECEPCION"] = ""
        base["OBS_RECEPCION"] = ""
    else:
        st_df = st_df.rename(
            columns={
                "orden": "ORDEN",
                "entregado": "ENTREGADO",
                "fecha_hora_entrega": "FECHA_HORA_ENTREGA",
                "usuario_entrega": "USUARIO_ENTREGA",
                "obs_entrega": "OBS_ENTREGA",
                "recibido_bodega": "RECIBIDO_BODEGA",
                "fecha_hora_finalizacion": "FECHA Y HORA DE FINALIZACION",
                "usuario_recepcion": "USUARIO_RECEPCION",
                "obs_recepcion": "OBS_RECEPCION",
            }
        )
        base = base.merge(st_df, on="ORDEN", how="left")
        base["ENTREGADO"] = base["ENTREGADO"].fillna(0).astype(bool)
        base["RECIBIDO_BODEGA"] = base["RECIBIDO_BODEGA"].fillna(0).astype(bool)
        for c in [
            "FECHA_HORA_ENTREGA", "USUARIO_ENTREGA", "OBS_ENTREGA",
            "FECHA Y HORA DE FINALIZACION", "USUARIO_RECEPCION", "OBS_RECEPCION"
        ]:
            base[c] = base[c].fillna("").astype(str)

    def estado_lbl(row):
        if row["RECIBIDO_BODEGA"]:
            return "📦 Recibido en Bodega"
        if row["ENTREGADO"]:
            return "✅ Entregado"
        return "⏳ Pendiente"

    base["ESTADO"] = base.apply(estado_lbl, axis=1)
    base = apply_dynamic_eta(base, now_dt=now_dt)
    return base


def to_excel_bytes(df_export: pd.DataFrame, sheet_name: str = "Reporte") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()


def now_ec_str() -> str:
    sim_dt = st.session_state.get("sim_now_dt")
    dt = sim_dt if sim_dt is not None else datetime.now(TZ_EC)
    return dt.strftime("%d/%m/%Y %H:%M")


def sort_camiones(cam_list):
    def key_fn(x):
        s = str(x)
        return (0, int(s)) if s.isdigit() else (1, s)
    return sorted(cam_list, key=key_fn)
