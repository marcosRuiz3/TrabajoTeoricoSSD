#!/bin/bash
echo "Deteniendo procesos IceGrid y Python..."
killall icegridregistry icegridnode python3 2>/dev/null

echo "Limpiando bases de datos temporales..."
rm -rf db/ *.txt

echo "Limpieza completada."