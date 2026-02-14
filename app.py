import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - v19 Estable", page_icon="⚙️", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Falta la API Key en los Secrets.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN Y REPARACIÓN DE HOJA
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        sh = gc.open("BaseDatos_Taller")
        ws = sh.worksheet("Gastos")
        
        # --- AUTO-REPARACIÓN DE ENCABEZADOS ---
        # Si la hoja está vacía, insertamos los nombres de las columnas
        if not ws.row_values(1):
            columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
            ws.insert_row(columnas, 1)
            
        return sh
    except Exception as e:
        st.error(f"⚠️ Error de conexión: {e}")
        return None

# ==========================================
# 🧠 3. MOTOR DE MONEDA PARAGUAYA (ANTI-ERRORES)
# ==========================================
def limpiar_monto_py(valor, es_cantidad=False):
    if not valor: return 0.0
    # Limpiamos todo excepto números, puntos y comas
    s = str(valor).replace('Gs', '').replace('$', '').replace(' ', '').strip()
    
    try:
        if es_cantidad:
            # Lógica para cantidades (2.5 litros, 10 unidades)
            # Si tiene coma (ej: 2,5), la pasamos a punto
            s = s.replace(',', '.')
            # Si tiene más de un punto (ej: 1.000,50), quitamos el de miles
            if s.count('.') > 1:
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            # Lógica para DINERO (10.000, 150.500)
            # En el dinero de Paraguay, IGNORAMOS todos los puntos y comas
            # porque no usamos centavos habitualmente.
            s = s.replace('.', '').replace(',', '')
            return float(s)
    except:
        return 0.0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura. Devuelve un JSON con: fecha (YYYY-MM-DD), proveedor, nro_factura, y lista de items con (producto, cantidad, unitario, total)."},
                {"inline_data": {"mime_type": mime_type, "data": archivo_b64}}
            ]
        }]
    }
    try:
        response = requests.post(url, json=payload)
        res_json = response.json()
        texto_ia = res_json['candidates'][0]['content']['parts'][0]['text']
        texto_limpio = texto_ia.replace("```json", "").replace("```", "").strip()
        return json.loads(texto_limpio)
    except: return None

# ==========================================
# 🖥️ 4. INTERFAZ
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False
if 'temp_data' not in st.session_state: st.session_state.temp_data = None

if not st.session_state.auth:
    st.title("🔐 Acceso Taller Pro")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Ingresar"):
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["📥 Cargar Factura", "📊 Dashboard", "📅 Historial", "🚀 Salir"])

    if menu == "📥 Cargar Factura":
        st.title("📥 Digitalizar Factura")
        f = st.file_uploader("Subir factura", type=["pdf", "png", "jpg", "jpeg"])
        
        if f and st.button("1. Analizar Documento"):
            with st.spinner("🤖 Leyendo datos con Gemini 2.0..."):
                datos = analizar_factura_v1(f.getvalue(), f.type)
                if datos:
                    df_items = pd.DataFrame(datos['items'])
                    # Aplicamos la limpieza según el tipo de dato
                    df_items['cantidad'] = df_items['cantidad'].apply(lambda x: limpiar_monto_py(x, es_cantidad=True))
                    df_items['unitario'] = df_items['unitario'].apply(lambda x: limpiar_monto_py(x, es_cantidad=False))
                    df_items['total'] = df_items['total'].apply(lambda x: limpiar_monto_py(x, es_cantidad=False))
                    
                    st.session_state.temp_data = {
                        'fecha': datos.get('fecha', ""),
                        'proveedor': datos.get('proveedor', ""),
                        'nro_factura': datos.get('nro_factura', ""),
                        'df': df_items
                    }
                else: st.error("No se pudo leer la factura.")

        if st.session_state.temp_data:
            st.markdown("---")
            st.subheader("📝 Verificación y Corrección")
            c1, c2, c3 = st.columns(3)
            f_ed = c1.text_input("Fecha", st.session_state.temp_data['fecha'])
            p_ed = c2.text_input("Proveedor", st.session_state.temp_data['proveedor'])
            n_ed = c3.text_input("Nro. Factura", st.session_state.temp_data['nro_factura'])
            
            # Editor interactivo para corregir errores de la IA
            edited_df = st.data_editor(st.session_state.temp_data['df'], use_container_width=True)
            
            if st.button("2. Confirmar y Guardar", type="primary"):
                sh = conectar_sheets()
                if sh:
                    ws = sh.worksheet("Gastos")
                    try:
                        registros = ws.get_all_records()
                    except: # Si falla por falta de columnas o datos
                        registros = []
                    
                    df_actual = pd.DataFrame(registros)
                    for _, row in edited_df.iterrows():
                        # Generamos ID ÚNICO para evitar duplicados
                        nuevo_id = f"{p_ed}_{f_ed}_{n_ed}_{row['producto']}".upper().replace(" ", "")
                        
                        if not df_actual.empty and 'ID_Unico' in df_actual.columns:
                            if nuevo_id in df_actual['ID_Unico'].values:
                                st.warning(f"⚠️ Saltado: '{row['producto']}' ya existe.")
                                continue
                        
                        ws.append_row([
                            f_ed, p_ed, n_ed, row['producto'], 
                            row['cantidad'], "u", row['unitario'], row['total'],
                            st.session_state.user, nuevo_id, str(datetime.datetime.now())
                        ])
                    st.success("✅ Registro completado.")
                    st.session_state.temp_data = None
                    st.balloons()

    elif menu == "📊 Dashboard":
        st.title("📊 Análisis de Posventa")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            if not df.empty:
                df['total'] = pd.to_numeric(df['total'], errors='coerce')
                # Resumen de gastos por mes
                df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
                df_mes = df.groupby(df['Fecha'].dt.strftime('%Y-%m'))['total'].sum().reset_index()
                st.plotly_chart(px.line(df_mes, x='Fecha', y='total', title="Evolución de Gastos (Gs.)"))
            else: st.info("Sube facturas para ver los gráficos.")

    elif menu == "📅 Historial":
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
