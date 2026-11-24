# Dashboard de Analitica de Logs (PostgreSQL + Dash)

Aplicacion en Python y Dash conectada a `public.logs` en PostgreSQL para visualizar latencia, volumen de peticiones y errores.

## Requisitos previos

1. Instalar dependencias:
   `pip install -r requirements.txt`

2. Crear un archivo `.env` en la raiz del proyecto:
   `DATABASE_URL=postgresql://usuario:password@host:puerto/base_de_datos?sslmode=require`

## Ejecucion

Ejecutar en terminal:
`python app.py`

Abrir en el navegador la direccion local que indique Dash (por defecto `http://127.0.0.1:8050`).

## Funcionalidades

- Selector por servicio (`svc`): permite ver todos los servicios o filtrar uno especifico.
- Ventana temporal: `1h`, `3h` y `24h`, ancladas al ultimo registro (`MAX(ts)`) disponible para mantener datos visibles cuando no hay ingesta continua en vivo.
- Metricas: `Response time` (promedio), `Throughout (RPM)`, `Error count (4xx y 5xx)` y `P95 / P99 response time`.
- Actualizacion automatica: intervalos de `10s` y `60s` (ademas de pausa).
