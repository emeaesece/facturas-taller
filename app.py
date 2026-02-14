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
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro 2026", page_icon="⚙️", layout="wide")

try:
    api_key_env = st.secrets["GOOGLE_API_KEY"]
    client_ia = genai.Client(api_key=api_key_env)
except:
    st.error("❌ No se encontró la API Key en Secrets.")
    st.stop()

# ==========================================
# ☁️ 2. BASE DE DATOS
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
# 🧠 3. MOTOR IA REFORZADO (PRIORIDAD 1.5)
# ==========================================
def limpiar_monto_py(valor):
    if not valor: return 0.0
    try:
        s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').replace(',', '.')
        if s.count('.') > 1:
            partes = s.split('.')
            s = "".join(partes[:-1]) + "." + partes[-1]
        return float(s)
    except: return 0.0

def analizar_factura(archivo_bytes, mime_type):
    # CAMBIO CLAVE: Ponemos el 1.5 primero, el 8b después (que tiene más cuota) y el 2.0 al final
    modelos = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.0-flash"]
    prompt = "Analiza esta factura. Extrae en JSON: fecha (YYYY-MM-DD), proveedor, y items (producto, cantidad, unitario, total). SOLO JSON."
    
    for mod in modelos:
        try:
            response = client_ia.models.generate_content(
                model=mod,
                contents=[prompt, types.Part.from_bytes(data=archivo_bytes, mime_type=mime_type)]
            )
            txt = response.text.strip()
            if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
            elif "```" in txt: txt = txt.split("```")[1].split("```")[0]
            return json.loads(txt)
            
        except Exception as e:
            err_msg = str(e)
            # Si el error es por cuota (429), esperamos 3 segundos y probamos el siguiente modelo
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                st.warning(f"⚠️ Cuota agotada en {mod}. Saltando al siguiente motor...")
                time.sleep(3) 
                continue 
            else:
                st.error(f"❌ Error con {mod}: {err_msg}")
                return None
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
        if f and st.button("Procesar", type="primary"):
            with st.spinner("🧠 Leyendo factura..."):
                datos = analizar_factura(f.getvalue(), f.type)
                if datos:
                    sh = conectar_sheets()
                    if sh:
                        ws = sh.worksheet("Gastos")
                        for i in datos.get("items", []):
                            ws.append_row([
                                datos.get("fecha", ""), datos.get("proveedor", ""),
                                i.get("producto", ""), limpiar_monto_py(i.get("cantidad")),
                                "u", limpiar_monto_py(i.get("unitario")), limpiar_monto_py(i.get("total")),
                                st.session_state.user, str(datetime.datetime.now())
                            ])
                        st.success("✅ ¡Guardado!")
                else: st.error("No se pudo procesar. Intenta en 1 minuto.")

    elif menu == "📊 Historial":
        st.title("📊 Gastos Registrados")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
