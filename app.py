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
st.set_page_config(page_title="Gestión de Posventa - Taller", page_icon="⚙️", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Falta la API Key en los Secrets.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN Y UTILIDADES
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds).open("BaseDatos_Taller")
    except: return None

def limpiar_monto_py(valor, es_cantidad=False):
    """
    Tratamiento especial para moneda paraguaya y cantidades decimales.
    Si es_cantidad=True, preserva decimales.
    Si es moneda, asegura que 1.000 no se convierta en 1.
    """
    if not valor: return 0.0
    s = str(valor).replace('Gs', '').replace('$', '').replace(' ', '').strip()
    
    try:
        # Si el número tiene formato 1.000.000 (puntos como miles)
        if s.count('.') >= 1 and ',' not in s:
            # Si termina en .000 y estamos en moneda, es un separador de miles
            if not es_cantidad:
                s = s.replace('.', '')
            else:
                # Si es cantidad y tiene un solo punto, evaluamos si es decimal o mil
                if s.count('.') == 1:
                    partes = s.split('.')
                    if len(partes[-1]) == 3: # Probablemente mil (ej: 1.000 unidades)
                        s = s.replace('.', '')
                    else: # Probablemente decimal (ej: 2.5 litros)
                        pass 
        # Si tiene coma (ej: 1.500,50)
        elif ',' in s:
            s = s.replace('.', '').replace(',', '.')
            
        return float(s)
    except: return 0.0

# ==========================================
# 🧠 3. MOTOR IA (EXTRACCIÓN AMPLIADA)
# ==========================================
def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": """Analiza esta factura. Devuelve estrictamente un JSON con: 
                fecha (YYYY-MM-DD), proveedor, nro_factura, 
                y una lista de items con (producto, cantidad, unitario, total). 
                IMPORTANTE: En 'cantidad' mantén los decimales si el insumo es fraccionado (litros, kg, horas)."""},
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
    p = st.text_input("Pass", type="password")
    if st.button("Ingresar"):
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["📥 Cargar Compra", "📊 Dashboard", "📅 Historial", "🚀 Salir"])

    if menu == "📥 Cargar Compra":
        st.title("📥 Registro de Facturas")
        f = st.file_uploader("Subir factura", type=["pdf", "png", "jpg", "jpeg"])
        
        if f and st.button("1. Analizar Documento"):
            with st.spinner("🤖 Procesando..."):
                datos = analizar_factura_v1(f.getvalue(), f.type)
                if datos:
                    df_items = pd.DataFrame(datos['items'])
                    df_items['cantidad'] = df_items['cantidad'].apply(lambda x: limpiar_monto_py(x, True))
                    df_items['unitario'] = df_items['unitario'].apply(limpiar_monto_py)
                    df_items['total'] = df_items['total'].apply(limpiar_monto_py)
                    
                    st.session_state.temp_data = {
                        'fecha': datos.get('fecha', ""),
                        'proveedor': datos.get('proveedor', ""),
                        'nro_factura': datos.get('nro_factura', ""),
                        'df': df_items
                    }
                else: st.error("Error al leer factura.")

        if st.session_state.temp_data:
            st.markdown("---")
            st.subheader("📝 Verificación de Datos")
            c1, c2, c3 = st.columns(3)
            f_ed = c1.text_input("Fecha", st.session_state.temp_data['fecha'])
            p_ed = c2.text_input("Proveedor", st.session_state.temp_data['proveedor'])
            n_ed = c3.text_input("Nro. Factura", st.session_state.temp_data['nro_factura'])
            
            edited_df = st.data_editor(st.session_state.temp_data['df'], use_container_width=True)
            
            if st.button("2. Validar y Guardar", type="primary"):
                sh = conectar_sheets()
                if sh:
                    ws = sh.worksheet("Gastos")
                    registros_actuales = ws.get_all_records()
                    df_actual = pd.DataFrame(registros_actuales)
                    
                    # Columna ID para duplicados: Proveedor_Fecha_Factura_Producto
                    duplicados_encontrados = 0
                    
                    for _, row in edited_df.iterrows():
                        nuevo_id = f"{p_ed}_{f_ed}_{n_ed}_{row['producto']}".upper().replace(" ", "")
                        
                        # Buscamos si ya existe ese ID (creamos la lógica de comparación)
                        existe = False
                        if not df_actual.empty and 'ID_Unico' in df_actual.columns:
                            if nuevo_id in df_actual['ID_Unico'].values:
                                existe = True
                        
                        if existe:
                            st.warning(f"⚠️ El ítem '{row['producto']}' ya existe en esta factura. No se duplicará.")
                            duplicados_encontrados += 1
                        else:
                            ws.append_row([
                                f_ed, p_ed, n_ed, row['producto'], 
                                row['cantidad'], "u", row['unitario'], row['total'],
                                st.session_state.user, nuevo_id, str(datetime.datetime.now())
                            ])
                    
                    if duplicados_encontrados == 0:
                        st.success("✅ ¡Todo guardado con éxito!")
                        st.balloons()
                    st.session_state.temp_data = None

    elif menu == "📊 Dashboard":
        st.title("📊 Análisis de Gastos")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            if not df.empty:
                df['total'] = pd.to_numeric(df['total'], errors='coerce')
                # Top Gastos por Producto
                fig = px.bar(df.groupby('Producto')['total'].sum().nlargest(10).reset_index(), 
                             x='Producto', y='total', title="Top 10 Productos con Mayor Inversión")
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("Sin datos.")

    elif menu == "📅 Historial":
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
