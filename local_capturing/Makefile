# Makefile — local_capturing
# Usage:
#   make help
#   make simulate_network_traffic
#   make network_data_capturing
#   make sensor_data_creation

# ------------ Config ------------
PROJECT_DIR := /home/digital/Documents/local_capturing
PY_BIN      := /home/digital/miniconda3/envs/py311resilmesh/bin/python
SUDO        ?= sudo

CAPTURE_SCRIPT := capture_network_data.py     # needs sudo (pcap)
SENSOR_SCRIPT  := create_sensor_data.py
SIM_SCRIPT     := simulate_live_traffic.sh

# ------------ Pretty printing ------------
YELLOW := \033[33m
CYAN   := \033[36m
RESET  := \033[0m

.PHONY: help simulate_network_traffic network_data_capturing sensor_data_creation \
        check-python 
.DEFAULT_GOAL := help

help:
	@echo "$(CYAN)Available targets:$(RESET)"
	@echo "  $(YELLOW)simulate_network_traffic$(RESET) - Run $(SIM_SCRIPT)"
	@echo "  $(YELLOW)network_data_capturing$(RESET)   - Run $(CAPTURE_SCRIPT) (sudo)"
	@echo "  $(YELLOW)sensor_data_creation$(RESET)     - Run $(SENSOR_SCRIPT)"
	@echo ""
	@echo "$(CYAN)Config:$(RESET)"
	@echo "  PROJECT_DIR = $(PROJECT_DIR)"
	@echo "  PY_BIN      = $(PY_BIN)"

# ------------ Main targets ------------

simulate_network_traffic: 
	cd $(PROJECT_DIR) && bash $(SIM_SCRIPT)

network_data_capturing: check-python 
	$(SUDO) $(PY_BIN) $(PROJECT_DIR)/$(CAPTURE_SCRIPT) 

sensor_data_creation: check-python 
	$(PY_BIN) $(PROJECT_DIR)/$(SENSOR_SCRIPT) 

# ------------ Checks ------------

check-python:
	@command -v $(PY_BIN) >/dev/null 2>&1 || { \
		echo "Python not found at: $(PY_BIN)"; \
		exit 1; \
	}

