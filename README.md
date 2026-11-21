# Control Logístico de Material Electoral — Guayas 2026 (Streamlit)

Aplicativo web en Python + Streamlit conectado directamente a `Plan_Entrega_Material_Electoral_Ordenado-v21.xlsx`.

## 1. Ejecución local (sin configurar nada)
```bash
pip install -r requirements.txt
streamlit run app.py
```
* **Clave por defecto (Pestaña 2):** `GUAYAS2026`
* En modo local los cambios se guardan automáticamente en `estado_despacho_guayas.db` (SQLite).

## 2. Despliegue para Comandantes de Fuerzas (Streamlit Cloud + Supabase)
1. Suba esta carpeta a un repositorio en GitHub.
2. En **Supabase**, ejecute `schema_supabase.sql` en el *SQL Editor*.
3. En **Streamlit Community Cloud** (*App Settings → Secrets*), agregue:
```toml
ADMIN_PASSWORD = "TU_CLAVE_SEGURA_AQUI"
SUPABASE_URL = "https://tu-proyecto.supabase.co"
SUPABASE_KEY = "tu-anon-o-service-key"
```
Con eso, cada vez que marques un camión o recinto como **ENTREGADO** o **RECIBIDO EN BODEGA**, todos los comandantes verán el avance actualizado en tiempo real.
