#!/usr/bin/env bash

# Load .env variables (simple parser, ignores comments and empty lines)
if [[ -f ".env" ]]; then
  export $(grep -v '^#' .env | xargs)
fi

# Config (from .env)
NETWORK_INTERFACE="${IFACE}"
PCAP_FILE="${PCAP_FILE}"

# Colors
GREEN="\033[1;32m"
RED="\033[1;31m"
YELLOW="\033[1;33m"
NC="\033[0m" # No Color

# Header
echo -e "${GREEN}=== TCPREPLAY RUNNER ===${NC}"

# Check file exists
if [[ ! -f "$PCAP_FILE" ]]; then
    echo -e "${RED}Error:${NC} PCAP file not found: $PCAP_FILE"
    exit 1
fi

# Show what will be executed
echo -e "${YELLOW}Interface:${NC} $NETWORK_INTERFACE"
echo -e "${YELLOW}PCAP File:${NC} $PCAP_FILE"
echo -e "${GREEN}Running command:${NC}"
echo "  sudo tcpreplay --intf1=$NETWORK_INTERFACE $PCAP_FILE"
echo

echo "Replaying on loopback interface (lo)..."
sudo tcpreplay --intf1=$NETWORK_INTERFACE "$PCAP_FILE"
STATUS=$?

if [[ $STATUS -eq 0 ]]; then
    echo "✅ Replay completed successfully on lo."
else
    echo "❌ Replay failed with exit code $STATUS."
fi
