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
st.set_page_config(page_title="Taller Pro - v20 Estable", page_icon="⚙️", layout="wide")

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
        gc = gspread.authorize(creds)
        sh = gc.open("BaseDatos_Taller")
        ws = sh.worksheet("Gastos")
        
        # Reparación de encabezados si es necesario
        if not ws.row_values(1):
            columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
            ws.insert_row(columnas, 1)
        return sh
    except: return None

# ==========================================
# 🧠 3. MOTOR DE MONEDA Y CANTIDADES (FIX 2026)
# ==========================================
def limpiar_monto_py(valor, es_cantidad=False):
    """
    Lógica específica para el mercado paraguayo:
    - Cantidad: Mantiene decimales (ej: 2.5 litros).
    - Moneda: Elimina decimales y separadores (ej: 10.500,00 -> 10500).
    """
    if not valor: return 0
    # Limpiamos símbolos y espacios
    s = str(valor).replace('Gs', '').replace('$', '').replace(' ', '').strip()
    
    try:
        if es_cantidad:
            # Para cantidades fraccionadas (litros, horas, etc.)
            s = s.replace(',', '.') # Normalizamos coma a punto
            if s.count('.') > 1: # Si hay más de un punto (miles), quitamos los de miles
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            # Para MONEDA (Guaraníes)
            # 1. Si termina en ,00 o .00 (centavos), los eliminamos primero
            if s.endswith(',00') or s.endswith('.00'):
                s = s[:-3]
            # 2. Si termina en ,0 o .0, lo eliminamos
            elif s.endswith(',0') or s.endswith('.0'):
                s = s[:-2]
                
            # 3. Quitamos todos los separadores restantes para tener el número entero
            s = s.replace('.', '').replace(',', '')
            return int(float(s)) # Doble conversión para evitar errores de string
    except:
        return 0

def analizar_factura_v1(archivo_bytes, mime_type):
    # Usamos Gemini 2.0 Flash que es el modelo que confirmó tu llave
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura. Devuelve un JSON con: fecha (YYYY-MM-DD), proveedor, nro_factura, y lista de items con (producto, cantidad, unitario, total). Mantén decimales solo en cantidad si son necesarios."},
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
            with st.spinner("🤖 Procesando con Gemini 2.0..."):
                datos = analizar_factura_v1(f.getvalue(), f.type)
                if datos:
                    df_items = pd.DataFrame(datos['items'])
                    # APLICAMOS LA NUEVA LÓGICA DE LIMPIEZA
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
            st.subheader("📝 Verificación y Corrección Final")
            c1, c2, c3 = st.columns(3)
            f_ed = c1.text_input("Fecha", st.session_state.temp_data['fecha'])
            p_ed = c2.text_input("Proveedor", st.session_state.temp_data['proveedor'])
            n_ed = c3.text_input("Nro. Factura", st.session_state.temp_data['nro_factura'])
            
            # Editor interactivo: aquí puedes corregir si la IA se equivocó
            edited_df = st.data_editor(st.session_state.temp_data['df'], use_container_width=True)
            
            if st.button("2. Confirmar y Guardar", type="primary"):
                sh = conectar_sheets()
                if sh:
                    ws = sh.worksheet("Gastos")
                    try:
                        registros = ws.get_all_records()
                        df_actual = pd.DataFrame(registros)
                    except: df_actual = pd.DataFrame()

                    for _, row in edited_df.iterrows():
                        # Lógica de ID ÚNICO para evitar duplicados
                        nuevo_id = f"{p_ed}_{f_ed}_{n_ed}_{row['producto']}".upper().replace(" ", "")
                        
                        if not df_actual.empty and 'ID_Unico' in df_actual.columns:
                            if nuevo_id in df_actual['ID_Unico'].values:
                                st.warning(f"⚠️ Saltado: '{row['producto']}' ya existe en esta factura.")
                                continue
                        
                        ws.append_row([
                            f_ed, p_ed, n_ed, row['producto'], 
                            row['cantidad'], "u", row['unitario'], row['total'],
                            st.session_state.user, nuevo_id, str(datetime.datetime.now())
                        ])
                    st.success("✅ Registro completado exitosamente.")
                    st.session_state.temp_data = None
                    st.balloons()

    elif menu == "📊 Dashboard":
        st.title("📊 Análisis de Posventa")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            if not df.empty:
                df['total'] = pd.to_numeric(df['total'], errors='coerce')
                m1, m2 = st.columns(2)
                m1.metric("Total Invertido", f"{df['total'].sum():,.0f} Gs.")
                m2.metric("Compras este Mes", len(df))
                
                fig = px.pie(df, values='total', names='Proveedor', title="Distribución por Proveedor")
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("Sube facturas para ver el análisis.")

    elif menu == "📅 Historial":
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
