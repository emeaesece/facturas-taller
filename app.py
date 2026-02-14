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
st.set_page_config(page_title="Taller Cloud 2026", page_icon="🔧", layout="wide")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 10px; height: 3.5em; font-weight: bold; }
    .stDataFrame { border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# Inicialización de la IA (Sin forzar versión para evitar el 404)
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
        # Buscamos la sección gcp_service_account en los Secrets
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        return gc.open("BaseDatos_Taller")
    except Exception as e:
        st.error(f"⚠️ Error de conexión con Sheets: {e}")
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
# 🧠 3. MOTOR DE IA CON FALLBACK (ANTI-404)
# ==========================================
def limpiar_monto_py(valor):
    """Limpia formatos: 1.500.000 / 1.500,50 / 1500.50"""
    if not valor: return 0.0
    try:
        s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').strip()
        # Caso 1.250.000 (miles con punto)
        if '.' in s and ',' not in s:
            partes = s.split('.')
            if len(partes[-1]) == 3: s = s.replace('.', '')
        # Caso 1.250,50 (miles con punto, decimal con coma)
        elif '.' in s and ',' in s:
            s = s.replace('.', '').replace(',', '.')
        # Caso 1250,50 (decimal con coma)
        elif ',' in s:
            s = s.replace(',', '.')
        return float(s)
    except: return 0.0

def analizar_factura(archivo_bytes, mime_type):
    # Lista de modelos compatibles 2026
    modelos = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-latest"]
    prompt = """Analiza esta factura. Extrae en un JSON: 
    {
      "fecha": "YYYY-MM-DD", 
      "proveedor": "Nombre", 
      "items": [{"producto": "desc", "cantidad": 1, "unitario": 0, "total": 0}]
    }
    Devuelve SOLO el JSON, sin explicaciones."""
    
    for mod in modelos:
        try:
            response = client_ia.models.generate_content(
                model=mod,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=archivo_bytes, mime_type=mime_type)
                ]
            )
            # Limpiar respuesta por si la IA incluye markdown
            txt = response.text.strip()
            if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
            elif "```" in txt: txt = txt.split("```")[1].split("```")[0]
            
            return json.loads(txt)
        except Exception as e:
            if "404" in str(e): continue # Probar siguiente modelo
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
        else: st.error("Credenciales incorrectas.")
else:
    with st.sidebar:
        st.header(f"👤 {st.session_state.user}")
        menu = st.radio("Menú", ["📥 Cargar Factura", "📊 Ver Historial", "🚀 Salir"])

    if menu == "📥 Cargar Factura":
        st.title("📥 Registro de Compras")
        f = st.file_uploader("Subir PDF o Imagen", type=["pdf", "png", "jpg", "jpeg"])
        
        if f and st.button("Procesar Factura", type="primary"):
            with st.spinner("🧠 Analizando con IA..."):
                datos = analizar_factura(f.getvalue(), f.type)
                if datos and "items" in datos:
                    st.write("### Datos detectados:")
                    st.json(datos)
                    
                    sh = conectar_sheets()
                    if sh:
                        ws = sh.worksheet("Gastos")
                        count = 0
                        for i in datos["items"]:
                            # Guardar fila con números limpios
                            ws.append_row([
                                datos.get("fecha", ""),
                                datos.get("proveedor", ""),
                                i.get("producto", ""),
                                limpiar_monto_py(i.get("cantidad")),
                                "u",
                                limpiar_monto_py(i.get("unitario")),
                                limpiar_monto_py(i.get("total")),
                                st.session_state.user,
                                str(datetime.datetime.now())
                            ])
                            count += 1
                        st.success(f"✅ ¡Guardado! {count} items registrados.")
                else:
                    st.error("No se detectó información. Intenta con una imagen más clara.")

    elif menu == "Ver Historial":
        st.title("📊 Base de Datos")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)
            
    if menu == "🚀 Salir":
        st.session_state.sesion = False
        st.rerun()
