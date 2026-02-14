import streamlit as st
import pandas as pd
from google import genai # <--- Nuevo motor oficial 2026
import json
import time
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# ⚙️ 1. CONFIGURACIÓN (REFORZADA)
# ==========================================
st.set_page_config(page_title="Taller Cloud - Motor Nuevo", page_icon="⚙️", layout="wide")

# Intentar recuperar la clave de varias formas posibles
api_key_env = None

if "GOOGLE_API_KEY" in st.secrets:
    api_key_env = st.secrets["GOOGLE_API_KEY"]
elif "api_key" in st.secrets:
    api_key_env = st.secrets["api_key"]
elif "GEMINI_KEY" in st.secrets:
    api_key_env = st.secrets["GEMINI_KEY"]

if api_key_env:
    try:
        # Forzamos la versión v1 que es la más estable para producción
        client_ia = genai.Client(api_key=api_key_env, http_options={'api_version': 'v1'})
    except Exception as e:
        st.error(f"❌ Error al inicializar el cliente de IA: {e}")
        st.stop()
else:
    st.error("❌ ERROR CRÍTICO: No se encontró ninguna clave API en los Secrets.")
    st.info("""
    **Cómo solucionarlo:**
    1. Ve a los Settings de tu app en Streamlit Cloud.
    2. En 'Secrets', asegúrate de tener una línea que diga:
    `GOOGLE_API_KEY = "tu_clave_aqui"`
    """)
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN A GOOGLE SHEETS
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        return gc.open("BaseDatos_Taller")
    except Exception as e:
        st.error(f"Error Sheets: {e}")
        return None

# ==========================================
# 🧠 3. MOTOR IA (NUEVO SDK google.genai)
# ==========================================
def analizar_factura(archivo_bytes, mime_type):
    # Usamos el alias corto 'gemini-1.5-flash' o solo 'flash'
    try:
        response = client_ia.models.generate_content(
            model="gemini-1.5-flash", # Prueba cambiar a "gemini-1.5-flash" (sin v1beta)
            contents=[
                "Analiza esta factura y extrae los datos en JSON: fecha, proveedor, items (producto, cantidad, unitario, total).",
                {"mime_type": mime_type, "data": archivo_bytes}
            ],
            config={'response_mime_type': 'application/json'}
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"❌ Error de Llave o Conexión: {e}")
        return None

# ==========================================
# 🖥️ 4. INTERFAZ (IGUAL A LA ANTERIOR)
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Taller")
    u = st.text_input("Usuario")
    p = st.text_input("Pass", type="password")
    if st.button("Ingresar", width='stretch'):
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["Cargar", "Historial", "Salir"])
    
    if menu == "Cargar":
        st.title("📥 Cargar Factura")
        f = st.file_uploader("Subir", type=["pdf", "jpg", "png"])
        if f and st.button("Procesar con Motor Nuevo"):
            datos = analizar_factura(f.getvalue(), f.type)
            if datos:
                st.write("### Datos detectados:")
                st.json(datos)
                
                # Lógica de guardado en Sheets
                sh = conectar_sheets()
                if sh:
                    ws = sh.worksheet("Gastos")
                    for item in datos.get("items", []):
                        # Limpieza básica de números
                        def clean_n(n): return float(str(n).replace('.','').replace(',','.')) if n else 0
                        
                        ws.append_row([
                            datos.get("fecha"), datos.get("proveedor"),
                            item.get("producto"), clean_n(item.get("cantidad")),
                            "u", clean_n(item.get("unitario")), clean_n(item.get("total")),
                            st.session_state.user, str(datetime.datetime.now())
                        ])
                    st.success("✅ Guardado en la nube.")

    elif menu == "Historial":
        st.title("📊 Historial")
        try:
            sh = conectar_sheets()
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, width='stretch')
        except: st.error("No hay datos.")
        
    if menu == "Salir":
        st.session_state.auth = False
        st.rerun()


