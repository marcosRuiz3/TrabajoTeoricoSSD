#!/bin/bash

# 1. Crear carpetas para la base de datos de IceGrid
mkdir -p db/registry
mkdir -p db/node1
mkdir -p db/node2

# 2. Arrancar el Registry (El cerebro)
echo "Iniciando Registry..."
icegridregistry --Ice.Config=registry.config &
sleep 2

# 3. Arrancar los Nodos (Los trabajadores)
echo "Iniciando Nodo 1..."
icegridnode --Ice.Config=node1.config &
sleep 1

echo "Iniciando Nodo 2..."
icegridnode --Ice.Config=node2.config &
sleep 1

# 4. Desplegar la aplicación (Leer el XML)
echo "Desplegando Spotifice..."
icegridadmin --Ice.Default.Locator="IceGrid/Locator:tcp -h 127.0.0.1 -p 4061" \
             -u user -p pass \
             -e "application add spotifice.xml"

echo "✅ ¡Sistema desplegado! Abre 'icegridgui' para verlo."