import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
import json
import time
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# ⚙️ 1. CONFIGURACIÓN (OBLIGANDO A v1)
# ==========================================
st.set_page_config(page_title="Taller Pro 2026", page_icon="🔧", layout="wide")

try:
    api_key_env = st.secrets["GOOGLE_API_KEY"]
    # Forzamos la versión v1 de forma absoluta en la configuración inicial
    client_ia = genai.Client(
        api_key=api_key_env,
        http_options={'api_version': 'v1'} 
    )
except Exception as e:
    st.error(f"❌ Error al iniciar cliente: {e}")
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
        return gspread.authorize(creds).open("BaseDatos_Taller")
    except: return None

# ==========================================
# 🧠 3. MOTOR IA (SINTAXIS ULTRA-ESTABLE)
# ==========================================
def analizar_factura(archivo_bytes, mime_type):
    # Solo usamos los nombres que están confirmados en v1 producción
    modelos_estables = ["gemini-1.5-flash", "gemini-1.5-flash-8b"]
    prompt = "Analiza esta factura. Extrae un JSON con: fecha (YYYY-MM-DD), proveedor, y una lista de items con (producto, cantidad, unitario, total). SOLO JSON."
    
    for mod in modelos_estables:
        try:
            with st.spinner(f"🚀 Usando motor estable: {mod}..."):
                # Llamada directa sin configuraciones extra que puedan causar 404
                response = client_ia.models.generate_content(
                    model=mod,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=archivo_bytes, mime_type=mime_type)
                    ]
                )
                
                # Limpieza manual del JSON
                txt = response.text.strip()
                if "```json" in txt:
                    txt = txt.split("```json")[1].split("```")[0]
                elif "```" in txt:
                    txt = txt.split("```")[1].split("```")[0]
                
                return json.loads(txt)
                
        except Exception as e:
            # Si da error, lo mostramos discretamente y probamos el siguiente
            st.warning(f"⚠️ El motor {mod} no respondió. Probando alternativa...")
            time.sleep(1)
            continue
            
    st.error("❌ No hay conexión con los servidores de Google v1.")
    st.info("Sugerencia: Revisa en Google Cloud Console que la 'Generative Language API' esté activa.")
    return None

# ==========================================
# 🖥️ 4. INTERFAZ
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Taller Pro")
    u = st.text_input("Usuario")
    p = st.text_input("Pass", type="password")
    if st.button("Entrar", type="primary", width="stretch"):
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    with st.sidebar:
        st.header(f"🔧 {st.session_state.user}")
        menu = st.radio("Menú", ["📥 Cargar Compra", "📊 Historial", "🚀 Salir"])

    if menu == "📥 Cargar Compra":
        st.title("📥 Registro de Facturas")
        f = st.file_uploader("Subir PDF o Imagen", type=["pdf", "png", "jpg", "jpeg"])
        if f and st.button("Procesar Factura", type="primary"):
            datos = analizar_factura(f.getvalue(), f.type)
            if datos:
                sh = conectar_sheets()
                if sh:
                    ws = sh.worksheet("Gastos")
                    for i in datos.get("items", []):
                        # Limpieza básica para evitar errores de celdas
                        ws.append_row([
                            datos.get("fecha", ""),
                            datos.get("proveedor", ""),
                            i.get("producto", "Sin nombre"),
                            i.get("cantidad", 1),
                            "u",
                            i.get("unitario", 0),
                            i.get("total", 0),
                            st.session_state.user,
                            str(datetime.datetime.now())
                        ])
                    st.success("✅ ¡Factura guardada correctamente!")
                    st.balloons()
            else:
                st.error("La IA no pudo leer este archivo. Intenta con una foto más clara.")

    elif menu == "📊 Historial":
        st.title("📊 Base de Datos")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
