import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
import re

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - Gestión de Activos", page_icon="🔧", layout="wide")

if 'batch' not in st.session_state:
    st.session_state.batch = pd.DataFrame()

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Error: GOOGLE_API_KEY no configurada.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN Y GESTIÓN DE HOJAS
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        return gc.open("BaseDatos_Taller")
    except: return None

def obtener_o_crear_pestana(sh, nombre_usuario):
    nombre_hoja = f"Gasto-{nombre_usuario}"
    columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
    try:
        ws = sh.worksheet(nombre_hoja)
        headers = ws.row_values(1)
        if not headers or "ID_Unico" not in headers:
            ws.insert_row(columnas, 1)
        return ws
    except:
        ws = sh.add_worksheet(title=nombre_hoja, rows="3000", cols="20")
        ws.insert_row(columnas, 1)
        return ws

def limpiar_monto_py(valor, es_cantidad=False):
    if valor is None or str(valor).strip() == "": return 0
    s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').strip()
    try:
        if es_cantidad:
            s = s.replace(',', '.')
            if s.count('.') > 1:
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            s_solo_numeros = re.sub(r'\D', '', s)
            return int(s_solo_numeros) if s_solo_numeros else 0
    except: return 0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura de Paraguay. Extrae JSON: fecha (YYYY-MM-DD), proveedor, nro_factura, e items (producto, cantidad, unitario, total)."},
                {"inline_data": {"mime_type": mime_type, "data": archivo_b64}}
            ]
        }]
    }
    try:
        response = requests.post(url, json=payload, timeout=40)
        texto_ia = response.json()['candidates'][0]['content']['parts'][0]['text']
        return json.loads(texto_ia.replace("```json", "").replace("```", "").strip())
    except: return None

# ==========================================
# 🖥️ 4. INTERFAZ Y LÓGICA
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Sistema Taller")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar"):
        st.session_state.auth, st.session_state.user, st.session_state.rol = True, u, 'admin'
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["📥 Carga Masiva", "📊 Dashboard", "📅 Historial", "🚀 Salir"])
    sh = conectar_sheets()

    if menu == "📥 Carga Masiva":
        st.title(f"📥 Carga de Facturas")
        files = st.file_uploader("Subir archivos", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if files and st.button(f"Procesar {len(files)} archivos"):
            all_items = []
            bar = st.progress(0)
            for idx, f in enumerate(files):
                d = analizar_factura_v1(f.getvalue(), f.type)
                if d:
                    for it in d.get('items', []):
                        all_items.append({
                            'Fecha': d.get('fecha', ""), 'Proveedor': d.get('proveedor', ""),
                            'Factura': d.get('nro_factura', ""), 'Producto': it.get('producto', ""),
                            'Cantidad': limpiar_monto_py(it.get('cantidad'), True),
                            'Unitario': limpiar_monto_py(it.get('unitario')),
                            'Total': limpiar_monto_py(it.get('total'))
                        })
                bar.progress((idx + 1) / len(files))
            st.session_state.batch = pd.DataFrame(all_items)

        if not st.session_state.batch.empty:
            edited = st.data_editor(st.session_state.batch, use_container_width=True)
            if st.button("Guardar en la Nube", type="primary"):
                ws = obtener_o_crear_pestana(sh, st.session_state.user)
                df_actual = pd.DataFrame(ws.get_all_records())
                for _, r in edited.iterrows():
                    id_u = f"{r['Proveedor']}_{r['Fecha']}_{r['Factura']}_{r['Producto']}".upper().replace(" ", "")
                    if not df_actual.empty and 'ID_Unico' in df_actual.columns:
                        if id_u in df_actual['ID_Unico'].astype(str).values: continue
                    ws.append_row([str(r['Fecha']), str(r['Proveedor']), str(r['Factura']), str(r['Producto']), r['Cantidad'], "u", int(r['Unitario']), int(r['Total']), st.session_state.user, id_u, str(datetime.datetime.now())])
                st.success("✅ Guardado.")
                st.session_state.batch = pd.DataFrame()
                st.balloons()

    # --- MÓDULO 2: DASHBOARD (REPARADO) ---
    elif menu == "📊 Dashboard":
        st.title("📊 Indicadores de Gestión")
        dfs = []
        for h in sh.worksheets():
            if h.title.startswith("Gasto-"):
                data = h.get_all_records()
                if data: dfs.append(pd.DataFrame(data))
        
        df = pd.concat(dfs) if dfs else pd.DataFrame()

        if not df.empty:
            # Asegurar tipos de datos numéricos para el gráfico
            df['Total'] = pd.to_numeric(df['Total'], errors='coerce').fillna(0)
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
            
            c1, c2 = st.columns(2)
            c1.metric("Inversión Total", f"{df['Total'].sum():,.0f} Gs.")
            c2.metric("Registros Totales", len(df))

            st.markdown("---")
            # Gráfico de Gasto por Proveedor
            fig_pie = px.pie(df, values='Total', names='Proveedor', title="Inversión por Proveedor", hole=.4)
            st.plotly_chart(fig_pie, use_container_width=True)

            # Evolución Temporal
            df_time = df.groupby(df['Fecha'].dt.strftime('%Y-%m'))['Total'].sum().reset_index()
            fig_line = px.line(df_time, x='Fecha', y='Total', title="Tendencia Mensual de Gastos", markers=True)
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.info("No hay datos suficientes para mostrar el Dashboard.")

    # --- MÓDULO 3: HISTORIAL (CON FILTROS Y BUSCADOR) ---
    elif menu == "📅 Historial":
        st.title("📅 Historial de Gastos")
        ws = obtener_o_crear_pestana(sh, st.session_state.user)
        df = pd.DataFrame(ws.get_all_records())
        
        if not df.empty:
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
            
            # Filtros superiores
            col1, col2 = st.columns([2, 2])
            with col1:
                search = st.text_input("🔍 Buscar por Producto", "")
            with col2:
                fecha_rango = st.date_input("📅 Rango de Fechas", [])

            # Aplicar Buscador
            if search:
                df = df[df['Producto'].astype(str).str.contains(search, case=False, na=False)]
            
            # Aplicar Filtro de Fecha
            if len(fecha_rango) == 2:
                start, end = fecha_rango
                df = df[(df['Fecha'].dt.date >= start) & (df['Fecha'].dt.date <= end)]
            
            st.markdown("---")
            st.dataframe(df.sort_values(by="Fecha", ascending=False), use_container_width=True)
            st.info(f"Subtotal en vista actual: **{df['Total'].sum():,.0f} Gs.**")
        else:
            st.info("No hay registros en esta pestaña.")

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
