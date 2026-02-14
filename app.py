import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - v1 Producción", page_icon="🔧", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Falta la API Key en los Secrets de Streamlit.")
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
# 🧠 3. MOTOR IA (RUTA v1 PRODUCCIÓN)
# ==========================================
def analizar_factura_v1(archivo_bytes, mime_type):
    # CAMBIO CRÍTICO: Usamos /v1/ en lugar de /v1beta/
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={API_KEY}"
    
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    
    # Estructura de datos exacta para la API v1
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura de taller mecánico. Extrae y devuelve SOLO un JSON con: fecha (YYYY-MM-DD), proveedor, y una lista de items con (producto, cantidad, unitario, total)."},
                {"inline_data": {"mime_type": mime_type, "data": archivo_b64}}
            ]
        }]
    }
    
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        res_json = response.json()
        
        if response.status_code == 200:
            texto_ia = res_json['candidates'][0]['content']['parts'][0]['text']
            # Limpiamos posibles etiquetas de markdown
            texto_ia = texto_ia.replace("```json", "").replace("```", "").strip()
            return json.loads(texto_ia)
        else:
            # Reporte de error detallado
            msg = res_json.get('error', {}).get('message', 'Error desconocido')
            st.error(f"❌ Error {response.status_code}: {msg}")
            if "404" in str(response.status_code):
                st.warning("⚠️ Google dice que el modelo no existe en esta ruta. Revisa la activación de la API.")
            return None
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

# ==========================================
# 🖥️ 4. INTERFAZ DE USUARIO
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Sistema Taller")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Ingresar", type="primary"):
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    with st.sidebar:
        st.header(f"👤 {st.session_state.user}")
        menu = st.radio("Menú", ["📥 Cargar Compra", "📊 Historial", "🚀 Salir"])

    if menu == "📥 Cargar Compra":
        st.title("📥 Registro de Facturas (v1)")
        f = st.file_uploader("Subir PDF o Imagen", type=["pdf", "png", "jpg", "jpeg"])
        
        if f and st.button("Procesar con IA de Producción"):
            with st.spinner("🤖 Conectando con Google v1..."):
                datos = analizar_factura_v1(f.getvalue(), f.type)
                if datos:
                    st.write("### Datos detectados:")
                    st.json(datos)
                    sh = conectar_sheets()
                    if sh:
                        ws = sh.worksheet("Gastos")
                        for i in datos.get('items', []):
                            ws.append_row([
                                datos.get('fecha'), datos.get('proveedor'),
                                i.get('producto'), i.get('cantidad'),
                                "u", i.get('unitario'), i.get('total'),
                                st.session_state.user, str(datetime.datetime.now())
                            ])
                        st.success("✅ ¡Guardado en Google Sheets!")
                        st.balloons()
    
    elif menu == "📊 Historial":
        st.title("📊 Base de Datos")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()

import streamlit as st
import requests

st.title("🔍 Diagnóstico de Modelos Disponibles")

API_KEY = st.secrets["GOOGLE_API_KEY"]
url = f"https://generativelanguage.googleapis.com/v1/models?key={API_KEY}"

if st.button("Listar Modelos Permitidos"):
    try:
        response = requests.get(url)
        data = response.json()
        
        if response.status_code == 200:
            st.success("✅ Conexión exitosa. Estos son tus modelos:")
            # Listamos solo los nombres de los modelos
            modelos = [m['name'] for m in data.get('models', [])]
            st.write(modelos)
        else:
            st.error(f"❌ Error {response.status_code}: {data.get('error', {}).get('message')}")
    except Exception as e:
        st.error(f"Falló la conexión: {e}")
