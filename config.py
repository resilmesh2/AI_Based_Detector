import os
from dotenv import load_dotenv


# # Load environment variables from .env
# load_dotenv() ## correct that one

# # Base path for relative file paths
# BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# # --------- Helper Function for Strict Env Vars ---------
# def get_env_var(key):
#     value = os.getenv(key)
#     if value is None:
#         raise EnvironmentError(f"Missing required environment variable: {key}")
#     return value

# # --------- Edge Settings ---------
# EDGE_DETECTOR = get_env_var("EDGE_DETECTOR")
# EDGE_DEVICE_ID = get_env_var("EDGE_DEVICE_ID")



# # --------- Vector Settings ---------
# VECTOR_URL = get_env_var("VECTOR_URL")

# # --------- NATS Settings ---------
# NATS_SERVER = get_env_var("NATS_SERVER")
# NETWORK_SUBJECT = get_env_var("NETWORK_SUBJECT")
# SENSOR_SUBJECT = get_env_var("SENSOR_SUBJECT")


# # --------- File Paths (Relative to BASE_PATH) ---------
# def rel_path(env_var):
#     path = get_env_var(env_var)
#     return os.path.join(BASE_PATH, path)

# LOG_PATH = rel_path("LOG_PATH")

# SENSOR_MODEL = rel_path("SENSOR_MODEL")
# SENSOR_SCALER = rel_path("SENSOR_SCALER")

# NETWORK_MODEL = rel_path("NETWORK_MODEL")
# NETWORK_SCALER = rel_path("NETWORK_SCALER")

# NETWORK_FILE = rel_path("NETWORK_FILE")
# SENSOR_FILE = rel_path("SENSOR_FILE")

