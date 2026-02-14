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
st.set_page_config(page_title="Taller Pro - Emergencia", page_icon="🚨", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Falta GOOGLE_API_KEY en Secrets.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN SHEETS
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
# 🧠 3. MOTOR IA (CONEXIÓN DIRECTA POR HTTP)
# ==========================================
def analizar_factura_directo(archivo_bytes, mime_type):
    # Usamos la URL de producción más estable
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}"
    
    # Codificamos el archivo para enviarlo
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura. Devuelve solo un JSON con: fecha (YYYY-MM-DD), proveedor, y una lista de items con (producto, cantidad, unitario, total)."},
                {"inline_data": {"mime_type": mime_type, "data": archivo_b64}}
            ]
        }],
        "generationConfig": {
            "response_mime_type": "application/json",
        }
    }
    
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        res_json = response.json()
        
        if response.status_code == 200:
            # Extraemos el texto de la respuesta
            texto_ia = res_json['candidates'][0]['content']['parts'][0]['text']
            return json.loads(texto_ia)
        else:
            st.error(f"❌ Error del servidor ({response.status_code}): {res_json.get('error', {}).get('message')}")
            return None
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

# ==========================================
# 🖥️ 4. INTERFAZ
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso de Emergencia")
    u = st.text_input("Usuario")
    p = st.text_input("Pass", type="password")
    if st.button("Entrar"):
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["Cargar", "Historial", "Salir"])
    
    if menu == "Cargar":
        f = st.file_uploader("Subir factura", type=["pdf", "png", "jpg", "jpeg"])
        if f and st.button("Procesar Factura"):
            with st.spinner("🤖 Intentando conexión directa..."):
                datos = analizar_factura_directo(f.getvalue(), f.type)
                if datos:
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
                        st.success("✅ ¡Registrado con éxito!")
                        st.balloons()
    
    elif menu == "Historial":
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    if menu == "Salir":
        st.session_state.auth = False
        st.rerun()
