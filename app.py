import streamlit as st
import pandas as pd
from google import genai
from google.genai import types # IMPORTANTE: Para el formato de archivos
import json
import time
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Cloud 2026", page_icon="⚙️", layout="wide")

# Inicialización del Cliente IA con la nueva SDK
try:
    api_key_env = st.secrets["GOOGLE_API_KEY"]
    # Usamos la versión estable v1
    client_ia = genai.Client(api_key=api_key_env, http_options={'api_version': 'v1'})
except Exception as e:
    st.error("❌ Configura GOOGLE_API_KEY en los Secrets de Streamlit.")
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
# 🧠 3. MOTOR IA (SINTAXIS 2026 CORREGIDA)
# ==========================================
def analizar_factura(archivo_bytes, mime_type):
    prompt = """Analiza esta factura de taller. Extrae en JSON: fecha (YYYY-MM-DD), 
    proveedor, y lista de items con (producto, cantidad, unitario, total). 
    Limpia los números de puntos de miles para que sean procesables."""
    
    try:
        # CORRECCIÓN CLAVE: Envolviendo el archivo en types.Part.from_bytes
        response = client_ia.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                prompt,
                types.Part.from_bytes(data=archivo_bytes, mime_type=mime_type)
            ],
            config=types.GenerateContentConfig(response_mime_type='application/json')
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"❌ Error de validación o API: {e}")
        return None

# ==========================================
# 🖥️ 4. INTERFAZ DE USUARIO
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
    with st.sidebar:
        st.header(f"👤 {st.session_state.user}")
        menu = st.radio("Menú", ["Cargar Factura", "Ver Historial", "Salir"])

    if menu == "Cargar Factura":
        st.title("📥 Cargar Compra")
        f = st.file_uploader("Sube PDF o Imagen", type=["pdf", "jpg", "png", "jpeg"])
        
        if f and st.button("Procesar Factura"):
            with st.spinner("🤖 La IA está leyendo el documento..."):
                datos = analizar_factura(f.getvalue(), f.type)
                
                if datos:
                    st.write("### Datos detectados:")
                    st.json(datos)
                    
                    sh = conectar_sheets()
                    if sh:
                        ws = sh.worksheet("Gastos")
                        # Función para limpiar números latinos
                        def clean_val(v):
                            if not v: return 0.0
                            try:
                                s = str(v).replace('.','').replace(',','.')
                                return float(s)
                            except: return 0.0

                        for item in datos.get("items", []):
                            ws.append_row([
                                datos.get("fecha"),
                                datos.get("proveedor"),
                                item.get("producto"),
                                clean_val(item.get("cantidad")),
                                "u",
                                clean_val(item.get("unitario")),
                                clean_val(item.get("total")),
                                st.session_state.user,
                                str(datetime.datetime.now())
                            ])
                        st.success("✅ ¡Guardado exitosamente en Google Sheets!")

    elif menu == "Ver Historial":
        st.title("📊 Historial de Compras")
        try:
            sh = conectar_sheets()
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, width='stretch')
        except:
            st.info("No hay datos todavía.")
            
    if menu == "Salir":
        st.session_state.auth = False
        st.rerun()
