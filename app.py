import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
import json
import time
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import io

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - Diagnóstico", page_icon="🔧", layout="wide")

try:
    api_key_env = st.secrets["GOOGLE_API_KEY"]
    # Probamos inicializar sin forzar versión para ver qué decide el servidor
    client_ia = genai.Client(api_key=api_key_env)
except Exception as e:
    st.error(f"❌ Error de inicialización: {e}")
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
# 🧠 3. MOTOR IA CON REPORTE DE ERRORES
# ==========================================
def analizar_factura(archivo_bytes, mime_type):
    # Lista extendida de modelos para 2026
    modelos = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-2.0-flash-exp"]
    prompt = "Analiza esta factura. Extrae un JSON: {fecha: YYYY-MM-DD, proveedor: texto, items: [{producto, cantidad, unitario, total}]}. SOLO JSON."
    
    reporte_errores = []
    
    for mod in modelos:
        try:
            with st.spinner(f"🕵️ Probando con {mod}..."):
                response = client_ia.models.generate_content(
                    model=mod,
                    contents=[prompt, types.Part.from_bytes(data=archivo_bytes, mime_type=mime_type)]
                )
                txt = response.text.strip()
                if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
                elif "```" in txt: txt = txt.split("```")[1].split("```")[0]
                return json.loads(txt)
        except Exception as e:
            reporte_errores.append(f"🔴 {mod}: {str(e)}")
            time.sleep(1)
            continue
    
    # Si todos fallan, mostramos el reporte detallado
    st.error("❌ Ningún modelo respondió después de 8 horas de espera.")
    with st.expander("🔍 VER REPORTE TÉCNICO DE BLOQUEO"):
        for err in reporte_errores:
            st.write(err)
        st.warning("Si todos los errores son 403 o 404, tu API Key no tiene permiso para estos modelos.")
    return None

# ==========================================
# 🖥️ 4. INTERFAZ
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Taller")
    u = st.text_input("Usuario")
    p = st.text_input("Pass", type="password")
    if st.button("Entrar", type="primary"):
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["📥 Cargar", "📊 Historial", "🚀 Salir"])

    if menu == "📥 Cargar":
        f = st.file_uploader("Subir factura", type=["pdf", "png", "jpg"])
        if f and st.button("Procesar Factura"):
            datos = analizar_factura(f.getvalue(), f.type)
            if datos:
                sh = conectar_sheets()
                if sh:
                    ws = sh.worksheet("Gastos")
                    for i in datos.get("items", []):
                        ws.append_row([
                            datos.get("fecha", ""), datos.get("proveedor", ""),
                            i.get("producto", ""), i.get("cantidad", 1),
                            "u", i.get("unitario", 0), i.get("total", 0),
                            st.session_state.user, str(datetime.datetime.now())
                        ])
                    st.success("✅ Guardado en la nube.")

    elif menu == "📊 Historial":
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
