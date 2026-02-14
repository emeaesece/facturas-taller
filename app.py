import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px # Para gráficos más profesionales

# ==========================================
# ⚙️ 1. CONFIGURACIÓN Y ESTILOS
# ==========================================
st.set_page_config(page_title="Taller Pro Dashboard", page_icon="📊", layout="wide")

st.markdown("""
    <style>
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #dee2e6; }
    .stButton>button { width: 100%; border-radius: 10px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Falta la API Key en los Secrets.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN GOOGLE SHEETS
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds).open("BaseDatos_Taller")
    except: return None

# ==========================================
# 🧠 3. MOTOR DE LIMPIEZA DECIMAL
# ==========================================
def limpiar_decimal_py(valor):
    """Mantiene decimales para cantidades fraccionadas (litros, horas, etc.)"""
    if not valor: return 0.0
    try:
        # Convertimos a string y limpiamos caracteres no numéricos excepto puntos y comas
        s = str(valor).replace(' ', '').replace('Gs', '').replace('$', '')
        # Si tiene coma como decimal (ej: 2,5), la pasamos a punto
        if ',' in s and '.' not in s:
            s = s.replace(',', '.')
        # Si tiene puntos de miles y coma decimal (ej: 1.500,50)
        elif '.' in s and ',' in s:
            s = s.replace('.', '').replace(',', '.')
        # Si tiene puntos de miles pero no decimal (ej: 1.500)
        elif '.' in s and len(s.split('.')[-1]) == 3:
            s = s.replace('.', '')
        return float(s)
    except: return 0.0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura. Devuelve un JSON con: fecha (YYYY-MM-DD), proveedor, y lista de items con (producto, cantidad, unitario, total). Mantén los decimales en cantidad si existen."},
                {"inline_data": {"mime_type": mime_type, "data": archivo_b64}}
            ]
        }]
    }
    
    try:
        response = requests.post(url, json=payload)
        res_json = response.json()
        texto_ia = res_json['candidates'][0]['content']['parts'][0]['text']
        texto_limpio = texto_ia.replace("```json", "").replace("```", "").strip()
        return json.loads(texto_limpio)
    except: return None

# ==========================================
# 🖥️ 4. INTERFAZ Y FLUJO DE TRABAJO
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False
if 'temp_data' not in st.session_state: st.session_state.temp_data = None

if not st.session_state.auth:
    st.title("🔐 Acceso Taller Pro")
    u = st.text_input("Usuario")
    p = st.text_input("Pass", type="password")
    if st.button("Ingresar"):
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    menu = st.sidebar.radio("Navegación", ["📥 Cargar Factura", "📊 Dashboard", "📅 Historial", "🚀 Salir"])

    # --- MÓDULO 1: CARGA CON EDICIÓN ---
    if menu == "📥 Cargar Factura":
        st.title("📥 Digitalizar Compra")
        f = st.file_uploader("Subir factura", type=["pdf", "png", "jpg", "jpeg"])
        
        if f and st.button("1. Analizar con IA"):
            with st.spinner("🤖 Leyendo documento..."):
                datos = analizar_factura_v1(f.getvalue(), f.type)
                if datos:
                    # Convertimos a DataFrame para permitir edición
                    df_items = pd.DataFrame(datos['items'])
                    df_items['cantidad'] = df_items['cantidad'].apply(limpiar_decimal_py)
                    df_items['unitario'] = df_items['unitario'].apply(limpiar_decimal_py)
                    df_items['total'] = df_items['total'].apply(limpiar_decimal_py)
                    
                    st.session_state.temp_data = {
                        'fecha': datos.get('fecha', str(datetime.date.today())),
                        'proveedor': datos.get('proveedor', 'Desconocido'),
                        'df': df_items
                    }
                else: st.error("No se pudo leer el archivo.")

        if st.session_state.temp_data is not None:
            st.markdown("---")
            st.subheader("📝 Revisión de Datos")
            
            col_f, col_p = st.columns(2)
            fecha_edit = col_f.text_input("Fecha", st.session_state.temp_data['fecha'])
            prov_edit = col_p.text_input("Proveedor", st.session_state.temp_data['proveedor'])
            
            st.info("💡 Puedes hacer doble clic en las celdas de abajo para corregir cualquier dato.")
            edited_df = st.data_editor(st.session_state.temp_data['df'], use_container_width=True, num_rows="dynamic")
            
            if st.button("2. Confirmar y Guardar en Sheets", type="primary"):
                sh = conectar_sheets()
                if sh:
                    ws = sh.worksheet("Gastos")
                    with st.spinner("Guardando..."):
                        for _, row in edited_df.iterrows():
                            ws.append_row([
                                fecha_edit, prov_edit, row['producto'], 
                                row['cantidad'], "u", row['unitario'], row['total'],
                                st.session_state.user, str(datetime.datetime.now())
                            ])
                    st.success("✅ ¡Datos guardados perfectamente!")
                    st.session_state.temp_data = None
                    st.balloons()

    # --- MÓDULO 2: DASHBOARD ---
    elif menu == "📊 Dashboard":
        st.title("📊 Indicadores de Gestión")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            if not df.empty:
                df['total'] = pd.to_numeric(df['total'], errors='coerce')
                df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
                
                # Métricas Rápidas
                m1, m2, m3 = st.columns(3)
                m1.metric("Gasto Total", f"{df['total'].sum():,.0f} Gs.")
                m2.metric("Proveedores Activos", df['Proveedor'].nunique())
                m3.metric("Última Compra", df['Fecha'].max().strftime('%d/%m/%Y'))

                # Gráfico de Gasto por Proveedor
                st.subheader("💰 Inversión por Proveedor")
                fig_prov = px.pie(df, values='total', names='Proveedor', hole=.3)
                st.plotly_chart(fig_prov, use_container_width=True)
                
                # Tendencia de Gastos
                st.subheader("📈 Tendencia Mensual")
                df_time = df.groupby(df['Fecha'].dt.strftime('%Y-%m'))['total'].sum().reset_index()
                st.line_chart(df_time.set_index('Fecha'))
            else: st.info("No hay datos suficientes para el Dashboard.")

    elif menu == "📅 Historial":
        st.title("📅 Historial Completo")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
