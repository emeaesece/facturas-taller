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
# ⚙️ 1. CONFIGURACIÓN Y ESTILOS
# ==========================================
st.set_page_config(page_title="Taller Cloud 2026", page_icon="⚙️", layout="wide")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 10px; height: 3.5em; font-weight: bold; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b; }
    </style>
    """, unsafe_allow_html=True)

# Inicializar contadores de sesión para el Panel de Control
if 'consultas_exitosas' not in st.session_state: st.session_state.consultas_exitosas = 0
if 'consultas_fallidas' not in st.session_state: st.session_state.consultas_fallidas = 0

try:
    api_key_env = st.secrets["GOOGLE_API_KEY"]
    client_ia = genai.Client(api_key=api_key_env)
except Exception as e:
    st.error("❌ ERROR: No se encontró GOOGLE_API_KEY en los Secrets.")
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
        st.error(f"⚠️ Error Sheets: {e}")
        return None

def check_login(u, p):
    try:
        sh = conectar_sheets()
        ws = sh.worksheet("Usuarios")
        for row in ws.get_all_records():
            if str(row['username']) == str(u) and str(row['password']) == str(p):
                return True
        return False
    except: return False

# ==========================================
# 🧠 3. MOTOR DE IA CON MONITOR DE USO
# ==========================================
def limpiar_monto_py(valor):
    if not valor: return 0.0
    try:
        s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').replace(',', '.')
        # Si hay más de un punto (ej: 1.500.000), dejamos solo el último para decimales
        if s.count('.') > 1:
            partes = s.split('.')
            s = "".join(partes[:-1]) + "." + partes[-1]
        return float(s)
    except: return 0.0

def analizar_factura(archivo_bytes, mime_type):
    modelos = ["gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-2.0-flash"]
    prompt = "Analiza esta factura de taller. Extrae en JSON: fecha (YYYY-MM-DD), proveedor, y lista de items (producto, cantidad, unitario, total). Devuelve SOLO JSON."
    
    for mod in modelos:
        try:
            response = client_ia.models.generate_content(
                model=mod,
                contents=[prompt, types.Part.from_bytes(data=archivo_bytes, mime_type=mime_type)]
            )
            txt = response.text.strip()
            if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
            elif "```" in txt: txt = txt.split("```")[1].split("```")[0]
            
            st.session_state.consultas_exitosas += 1
            return json.loads(txt)
        except Exception as e:
            if "404" in str(e) or "429" in str(e): 
                continue 
            st.session_state.consultas_fallidas += 1
            st.error(f"Error con modelo {mod}: {e}")
            return None
    return None

# ==========================================
# 🖥️ 4. INTERFAZ DE USUARIO (UI)
# ==========================================
if 'sesion' not in st.session_state: st.session_state.sesion = False

if not st.session_state.sesion:
    st.title("🔐 Acceso Taller Cloud")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Ingresar Sistema", type="primary"):
        if check_login(u, p):
            st.session_state.sesion = True
            st.session_state.user = u
            st.rerun()
        else: st.error("Acceso incorrecto.")
else:
    with st.sidebar:
        st.header(f"👤 {st.session_state.user}")
        menu = st.radio("Navegación", ["📥 Cargar Factura", "📊 Ver Historial", "🎛️ Panel de Control IA", "🚀 Salir"])

    # --- MÓDULO: CARGAR FACTURA ---
    if menu == "📥 Cargar Factura":
        st.title("📥 Registro de Compras")
        f = st.file_uploader("Subir PDF o Imagen", type=["pdf", "png", "jpg", "jpeg"])
        if f and st.button("Procesar Factura", type="primary"):
            with st.spinner("🤖 Analizando..."):
                datos = analizar_factura(f.getvalue(), f.type)
                if datos and "items" in datos:
                    sh = conectar_sheets()
                    if sh:
                        ws = sh.worksheet("Gastos")
                        for i in datos["items"]:
                            ws.append_row([
                                datos.get("fecha", ""), datos.get("proveedor", ""),
                                i.get("producto", ""), limpiar_monto_py(i.get("cantidad")),
                                "u", limpiar_monto_py(i.get("unitario")), limpiar_monto_py(i.get("total")),
                                st.session_state.user, str(datetime.datetime.now())
                            ])
                        st.success("✅ ¡Factura guardada con éxito!")
                else: st.error("Error al procesar. Revisa el Panel de Control.")

    # --- MÓDULO: HISTORIAL ---
    elif menu == "📊 Ver Historial":
        st.title("📊 Base de Datos de Gastos")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    # --- NUEVO MÓDULO: PANEL DE CONTROL IA ---
    elif menu == "🎛️ Panel de Control IA":
        st.title("🎛️ Monitor de Créditos y Salud de la IA")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Consultas Exitosas", st.session_state.consultas_exitosas)
        with col2:
            st.metric("Errores de Cuota", st.session_state.consultas_fallidas)
        with col3:
            st.metric("Plan Actual", "Gratis (Free)")

        st.markdown("---")
        st.subheader("⚠️ Límites del Plan Gratuito (Gemini 1.5 Flash)")
        st.write("""
        * **15 Consultas por minuto:** No subas más de 15 facturas al mismo tiempo.
        * **1,500 Consultas por día:** Tienes margen de sobra para el taller.
        * **Costo:** $0.00 (Gratis).
        """)
