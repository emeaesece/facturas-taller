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

# Inyectar un poco de estilo para que se vea mejor en móviles
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 10px; height: 3em; }
    </style>
    """, unsafe_allow_html=True)
# Recuperar API Key de Gemini
try:
    GEMINI_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    GEMINI_KEY = "TAIzaSyDBTsVTGgj9Ne_vQ-wyr9WaT0Zmsfyavbo"

genai.configure(api_key=GEMINI_KEY)

# ==========================================
# ☁️ 2. MOTOR DE GOOGLE SHEETS
# ==========================================

def conectar_sheets():
    """Establece conexión con la base de datos en la nube"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # Nombre exacto de tu archivo en Drive
        return client.open("BaseDatos_Taller")
    except Exception as e:
        st.error(f"Error de conexión con Google Sheets: {e}")
        return None

def check_login(u, p):
    """Verifica credenciales en la pestaña 'Usuarios'"""
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
    """Inserta una fila en la pestaña 'Gastos'"""
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
    except Exception as e:
        st.error(f"Error al guardar: {e}")
        return False

# ==========================================
# 🧠 3. MOTOR DE INTELIGENCIA ARTIFICIAL
# ==========================================

def analizar_factura(archivo_bytes, mime_type):
    """Extrae datos usando Gemini 1.5 Flash"""
    # Usamos el nombre de modelo más compatible
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = """
    Extrae los items de esta factura de taller. 
    Devuelve un JSON estrictamente con este formato:
    {
        "fecha": "YYYY-MM-DD",
        "proveedor": "Nombre",
        "items": [
            {"producto": "Desc", "cantidad": 0.0, "unidad": "u", "unitario": 0.0, "total": 0.0}
        ]
    }
    """
    try:
        response = model.generate_content([prompt, {"mime_type": mime_type, "data": archivo_bytes}])
        # Limpiar respuesta para obtener solo el JSON
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

# --- PANTALLA DE ACCESO ---
if not st.session_state.sesion:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🔐 Gestión Taller Cloud")
        user_in = st.text_input("Usuario")
        pass_in = st.text_input("Contraseña", type="password")
        
        # Uso de width='stretch' según requerimiento 2026
        if st.button("Entrar al Sistema", type="primary", width='stretch'):
            if check_login(user_in, pass_in):
                st.session_state.sesion = True
                st.session_state.user = user_in
                st.rerun()
            else:
                st.error("Credenciales incorrectas")

# --- PANTALLA PRINCIPAL ---
else:
    with st.sidebar:
        st.header(f"👤 {st.session_state.user}")
        menu = st.radio("Menu", ["📥 Cargar Compra", "📊 Historial", "🚀 Salir"])
        
        if menu == "🚀 Salir":
            st.session_state.sesion = False
            st.rerun()

    # --- MÓDULO CARGA ---
    if menu == "📥 Cargar Compra":
        st.title("📥 Digitalizar Factura")
        files = st.file_uploader("Sube fotos o PDFs", accept_multiple_files=True)
        
        if files and st.button("Analizar y Guardar", type="primary", width='stretch'):
            bar = st.progress(0)
            status = st.empty()
            count = 0
            
            for i, f in enumerate(files):
                bar.progress((i+1)/len(files))
                status.write(f"⚙️ Procesando: {f.name}...")
                
                data = analizar_factura(f.getvalue(), f.type)
                if data:
                    fecha_f = data.get("fecha", str(datetime.date.today()))
                    prov_f = data.get("proveedor", "Desconocido")
                    
                    for item in data.get("items", []):
                        obj = {
                            "Fecha": fecha_f, "Proveedor": prov_f,
                            "Producto": item.get("producto"),
                            "Cantidad": item.get("cantidad", 0),
                            "Unidad": item.get("unidad", "u"),
                            "Precio Unitario": item.get("unitario", 0),
                            "Precio Total": item.get("total", 0)
                        }
                        if guardar_en_nube(obj, st.session_state.user):
                            count += 1
                time.sleep(1)
            
            status.empty()
            st.success(f"✅ ¡Hecho! Se registraron {count} items en Google Sheets.")

    # --- MÓDULO HISTORIAL ---
    elif menu == "📊 Historial":
        st.title("📊 Consultar Precios")
        search = st.text_input("🔍 Buscar repuesto o proveedor...")
        
        try:
            sh = conectar_sheets()
            ws = sh.worksheet("Gastos")
            df = pd.DataFrame(ws.get_all_records())
            
            if not df.empty:
                if search:
                    df = df[df.apply(lambda r: r.astype(str).str.contains(search, case=False).any(), axis=1)]
                
                # Visualización con ancho elástico para 2026
                st.dataframe(
                    df, 
                    column_config={
                        "Precio Total": st.column_config.NumberColumn(format="$ %.2f"),
                        "Precio Unitario": st.column_config.NumberColumn(format="$ %.2f"),
                        "Fecha": st.column_config.DateColumn()
                    },
                    width='stretch'
                )
            else:
                st.info("No hay datos cargados todavía.")
        except:
            st.error("No se pudo leer la base de datos.")