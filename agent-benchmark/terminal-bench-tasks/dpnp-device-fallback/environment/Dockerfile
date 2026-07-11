# intel/oneapi-basekit provides DPC++ runtime and OpenCL CPU driver
# (OCL_ICD_FILENAMES) required for dpnp to discover the CPU SYCL device.
FROM intel/oneapi-basekit:latest

# dpctl and numpy are pulled in automatically as dpnp dependencies.
RUN python3 -m pip install --no-cache-dir dpnp pytest

COPY reference.py /app/reference.py
