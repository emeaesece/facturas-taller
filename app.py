import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import time
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# ⚙️ 1. CONFIGURACIÓN Y ESTILOS
# ==========================================

st.set_page_config(
    page_title="Taller Pro Cloud 2026", 
    page_icon="🔧", 
    layout="wide"
)

# Estilo para botones grandes y legibles
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 10px; height: 3em; }
    </style>
    """, unsafe_allow_html=True)

# Recuperar API Key de Gemini
try:
    GEMINI_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    GEMINI_KEY = "TU_CLAVE_LOCAL_AQUI"

genai.configure(api_key=GEMINI_KEY)

# ==========================================
# ☁️ 2. MOTOR DE GOOGLE SHEETS
# ==========================================

def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client.open("BaseDatos_Taller")
    except Exception as e:
        st.error(f"Error de conexión con Google Sheets: {e}")
        return None

def check_login(u, p):
    try:
        sh = conectar_sheets()
        ws = sh.worksheet("Usuarios")
        usuarios = ws.get_all_records()
        for user in usuarios:
            if str(user['username']) == str(u) and str(user['password']) == str(p):
                return True
        return False
    except:
        return False

def guardar_en_nube(item, usuario):
    try:
        sh = conectar_sheets()
        ws = sh.worksheet("Gastos")
        fila = [
            item['Fecha'], item['Proveedor'], item['Producto'], 
            item['Cantidad'], item['Unidad'], item['Precio Unitario'], 
            item['Precio Total'], usuario, str(datetime.datetime.now())
        ]
        ws.append_row(fila)
        return True
    except:
        return False

# ==========================================
# 🧠 3. MOTOR DE INTELIGENCIA ARTIFICIAL (REFORZADO)
# ==========================================

def analizar_factura(archivo_bytes, mime_type):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = """
    Eres un experto contable de taller mecánico. Analiza esta imagen de factura.
    Busca CUALQUIER tabla o lista de productos, repuestos o servicios.
    
    Extrae la información y devuélvela en este formato JSON EXACTO:
    {
        "fecha": "YYYY-MM-DD",
        "proveedor": "Nombre de la empresa",
        "items": [
            {
                "producto": "Nombre del repuesto",
                "cantidad": 1.0,
                "unidad": "u",
                "unitario": 0.0,
                "total": 0.0
            }
        ]
    }
    Si no hay cantidad, asume 1.0. Devuelve SOLO el JSON.
    """
    try:
        response = model.generate_content([prompt, {"mime_type": mime_type, "data": archivo_bytes}])
        raw_text = response.text.strip().replace("```json", "").replace("```", "")
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        return json.loads(raw_text[start:end])
    except:
        return None

# ==========================================
# 🖥️ 4. INTERFAZ DE USUARIO (UI)
# ==========================================

if 'sesion' not in st.session_state:
    st.session_state.sesion = False

if not st.session_state.sesion:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🔐 Acceso Taller Cloud")
        user_in = st.text_input("Usuario")
        pass_in = st.text_input("Contraseña", type="password")
        if st.button("Entrar", type="primary"):
            if check_login(user_in, pass_in):
                st.session_state.sesion = True
                st.session_state.user = user_in
                st.rerun()
            else:
                st.error("Credenciales incorrectas")
else:
    with st.sidebar:
        st.header(f"👤 {st.session_state.user}")
        menu = st.radio("Menú", ["📥 Cargar Compra", "📊 Historial", "🚀 Salir"])
        if menu == "🚀 Salir":
            st.session_state.sesion = False
            st.rerun()

    if menu == "📥 Cargar Compra":
        st.title("📥 Digitalizar Factura")
        files = st.file_uploader("Sube fotos o PDFs", accept_multiple_files=True)
        
        if files and st.button("Analizar y Guardar", type="primary"):
            bar = st.progress(0)
            status = st.empty()
            count = 0
            
            for i, f in enumerate(files):
                bar.progress((i+1)/len(files))
                status.write(f"⚙️ Procesando: {f.name}...")
                
                data = analizar_factura(f.getvalue(), f.type)
                
                # --- AQUÍ ESTABA EL ERROR DE INDENTACIÓN CORREGIDO ---
                if data and "items" in data:
                    fecha_f = data.get("fecha", str(datetime.date.today()))
                    prov_f = data.get("proveedor", "Desconocido")
                    items_lista = data.get("items", [])
                    
                    for item in items_lista:
                        obj = {
                            "Fecha": fecha_f,
                            "Proveedor": prov_f,
                            "Producto": item.get("producto", "Sin nombre"),
                            "Cantidad": float(item.get("cantidad", 1)),
                            "Unidad": item.get("unidad", "u"),
                            "Precio Unitario": float(item.get("unitario", 0)),
                            "Precio Total": float(item.get("total", 0))
                        }
                        if guardar_en_nube(obj, st.session_state.user):
                            count += 1
                time.sleep(1)
            
            status.empty()
            if count > 0:
                st.success(f"✅ Se registraron {count} items en Google Sheets.")
            else:
                st.warning("No se detectaron items. Intenta con una foto más clara.")

    elif menu == "📊 Historial":
        st.title("📊 Historial de Compras")
        search = st.text_input("🔍 Buscar repuesto...")
        try:
            sh = conectar_sheets()
            ws = sh.worksheet("Gastos")
            df = pd.DataFrame(ws.get_all_records())
            if not df.empty:
                if search:
                    df = df[df.apply(lambda r: r.astype(str).str.contains(search, case=False).any(), axis=1)]
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Sin datos.")
        except:
            st.error("Error al leer la base de datos.")
