import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import time
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Cloud - Modo Diagnóstico", page_icon="🔧", layout="wide")

try:
    GEMINI_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    GEMINI_KEY = "TU_CLAVE_LOCAL"

genai.configure(api_key=GEMINI_KEY)

# ==========================================
# ☁️ 2. CONEXIÓN A SHEETS
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
        st.error(f"Error de conexión: {e}")
        return None

# ==========================================
# 🧠 3. MOTOR DE IA Y LIMPIEZA REFORZADA
# ==========================================
def limpiar_monto_py(valor):
    """Limpia montos para el formato de Paraguay (1.500.000)"""
    if not valor: return 0.0
    try:
        # Convertir a string y quitar símbolos
        s = str(valor).upper().replace('GS', '').replace('.', '').replace(',', '.').strip()
        return float(s)
    except:
        return 0.0

def analizar_factura(archivo_bytes, mime_type):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = """Analiza esta factura. Extrae: fecha (YYYY-MM-DD), proveedor, y una lista de items con: producto, cantidad, unitario, total. Devuelve SOLAMENTE el JSON."""
    
    try:
        response = model.generate_content([prompt, {"mime_type": mime_type, "data": archivo_bytes}])
        texto_crudo = response.text.strip().replace("```json", "").replace("```", "")
        # Intentamos capturar el JSON
        inicio = texto_crudo.find("{")
        fin = texto_crudo.rfind("}") + 1
        return json.loads(texto_crudo[inicio:fin])
    except Exception as e:
        st.error(f"Error procesando JSON: {e}")
        st.write("Respuesta cruda de la IA:", response.text) # DIAGNÓSTICO
        return None

# ==========================================
# 🖥️ 4. INTERFAZ
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso")
    u = st.text_input("Usuario")
    p = st.text_input("Pass", type="password")
    if st.button("Entrar", width='stretch'):
        # Login simplificado para pruebas
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["Cargar", "Historial", "Salir"])
    
    if menu == "Cargar":
        st.title("📥 Cargar Factura")
        f = st.file_uploader("Subir archivo", type=["pdf", "jpg", "png"])
        
        if f and st.button("Procesar", width='stretch'):
            with st.spinner("Analizando..."):
                datos = analizar_factura(f.getvalue(), f.type)
                
                if datos:
                    # MOSTRAR LO QUE LA IA ENCONTRÓ ANTES DE GUARDAR
                    st.write("### 🔎 Datos detectados por la IA:")
                    st.json(datos)
                    
                    if "items" in datos and len(datos["items"]) > 0:
                        sh = conectar_sheets()
                        ws = sh.worksheet("Gastos")
                        
                        count = 0
                        for item in datos["items"]:
                            # Limpieza específica para los guaraníes/formatos con puntos
                            cant = limpiar_monto_py(item.get("cantidad", 1))
                            unit = limpiar_monto_py(item.get("unitario", 0))
                            total = limpiar_monto_py(item.get("total", 0))
                            
                            fila = [
                                datos.get("fecha", ""),
                                datos.get("proveedor", ""),
                                item.get("producto", ""),
                                cant,
                                item.get("unidad", "u"),
                                unit,
                                total,
                                st.session_state.user,
                                str(datetime.datetime.now())
                            ]
                            ws.append_row(fila)
                            count += 1
                        st.success(f"✅ Guardados {count} items en Google Sheets.")
                    else:
                        st.error("La IA no encontró la lista de productos dentro del archivo.")
                else:
                    st.error("No se pudo obtener una respuesta válida de la IA.")

    elif menu == "Historial":
        st.title("📊 Historial")
        try:
            sh = conectar_sheets()
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, width='stretch')
        except:
            st.error("Carga datos primero para ver el historial.")
            
    if menu == "Salir":
        st.session_state.auth = False
        st.rerun()
