#!/usr/bin/env bash
# =============================================================================
# FFmpeg Custom-Build: ALL System-Features + CUDA/NPP/NVENC
# =============================================================================
# Vereinigt die System-ffmpeg-Konfiguration (drawtext, vulkan, opencl, ...)
# mit dem Custom-Build (CUDA, CUVID, NVENC, NVDEC, libnpp, libfdk-aac).
#
# Nutzung:  sudo bash build_ffmpeg.sh
# =============================================================================
set -euo pipefail

CUDA_DIR="/usr/local/cuda-12.1"
FFMPEG_VERSION="7.1.1"
BUILD_DIR="/usr/local/src/ffmpeg_build"
NPROC=$(nproc)

echo "================================================"
echo "  FFmpeg ${FFMPEG_VERSION} Custom-Build"
echo "  CUDA: ${CUDA_DIR}"
echo "  Threads: ${NPROC}"
echo "================================================"

# --- 1) Vulkan SDK (LunarG) hinzufügen ------------------------------------------
echo ""
echo "==> Prüfe Vulkan SDK ..."
VULKAN_PKG_VER=$(pkg-config --modversion vulkan 2>/dev/null || echo "0")
if dpkg --compare-versions "${VULKAN_PKG_VER}" lt "1.3.277"; then
    echo "   Vulkan ${VULKAN_PKG_VER} zu alt (>= 1.3.277 benötigt), installiere LunarG SDK ..."
    apt-get install -y --no-install-recommends wget gnupg2
    wget -qO /etc/apt/keyrings/lunarg-signing-key-pub.asc \
        https://packages.lunarg.com/lunarg-signing-key-pub.asc
    echo "deb [signed-by=/etc/apt/keyrings/lunarg-signing-key-pub.asc] https://packages.lunarg.com/vulkan noble main" \
        > /etc/apt/sources.list.d/lunarg-vulkan-noble.list
    apt-get update -qq || echo "⚠️  apt-get update hatte Warnungen (wird ignoriert)"
    apt-get install -y --no-install-recommends vulkan-headers libvulkan-dev
    echo "   ✅ Vulkan SDK installiert: $(pkg-config --modversion vulkan 2>/dev/null)"
else
    echo "   ✅ Vulkan ${VULKAN_PKG_VER} bereits ausreichend"
fi

# --- 2) Dev-Pakete installieren -------------------------------------------------
echo ""
echo "==> Installiere fehlende Dev-Pakete ..."
apt-get update -qq || echo "⚠️  apt-get update hatte Warnungen (wird ignoriert)"

apt-get install -y --no-install-recommends \
    build-essential pkg-config nasm yasm git cmake \
    libfontconfig1-dev libfribidi-dev libharfbuzz-dev \
    libfreetype-dev libass-dev \
    libx264-dev libx265-dev libvpx-dev \
    libfdk-aac-dev libmp3lame-dev libopus-dev \
    libaom-dev libdav1d-dev libsvtav1enc-dev librav1e-dev \
    libvorbis-dev libtheora-dev libspeex-dev \
    libwebp-dev libjxl-dev \
    libxml2-dev librsvg2-dev \
    libbs2b-dev libcaca-dev libcdio-paranoia-dev \
    libcodec2-dev flite1-dev \
    libgme-dev libgsm1-dev libmysofa-dev \
    libopenjp2-7-dev libopenmpt-dev \
    librubberband-dev libshine-dev libsnappy-dev \
    libsoxr-dev libtwolame-dev libvidstab-dev \
    libxvidcore-dev libzimg-dev \
    libbluray-dev libdc1394-dev libdrm-dev \
    libiec61883-dev libavc1394-dev \
    libchromaprint-dev frei0r-plugins-dev \
    ladspa-sdk libjack-jackd2-dev \
    libpulse-dev librabbitmq-dev \
    librist-dev libsrt-gnutls-dev libssh-dev \
    libzmq3-dev libzvbi-dev \
    libplacebo-dev glslang-dev \
    libsdl2-dev libgnutls28-dev \
    liblilv-dev lilv-utils \
    libvulkan-dev ocl-icd-opencl-dev \
    pocketsphinx libpocketsphinx-dev \
    nvidia-opencl-dev \
    texinfo

echo "==> Dev-Pakete installiert."

# --- 2) Quellcode holen ---------------------------------------------------------
echo ""
echo "==> Hole FFmpeg ${FFMPEG_VERSION} Quellcode ..."
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

if [ ! -d "ffmpeg-${FFMPEG_VERSION}" ]; then
    wget -q "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" -O "ffmpeg-${FFMPEG_VERSION}.tar.xz"
    tar xf "ffmpeg-${FFMPEG_VERSION}.tar.xz"
    rm -f "ffmpeg-${FFMPEG_VERSION}.tar.xz"
fi
cd "ffmpeg-${FFMPEG_VERSION}"

# --- 3) Configure ---------------------------------------------------------------
echo ""
echo "==> Konfiguriere FFmpeg ..."

# Altes Build aufräumen
make distclean 2>/dev/null || true

./configure \
    --prefix=/usr/local \
    --enable-gpl \
    --enable-nonfree \
    --enable-version3 \
    \
    --enable-cuda \
    --enable-cuvid \
    --enable-nvenc \
    --enable-nvdec \
    --enable-libnpp \
    --extra-cflags="-I${CUDA_DIR}/include" \
    --extra-ldflags="-L${CUDA_DIR}/lib64" \
    \
    --enable-libx264 \
    --enable-libx265 \
    --enable-libvpx \
    --enable-libfdk-aac \
    --enable-libmp3lame \
    --enable-libopus \
    --enable-libass \
    --enable-libfreetype \
    \
    --enable-libfontconfig \
    --enable-libfribidi \
    --enable-libharfbuzz \
    \
    --enable-gnutls \
    --enable-libaom \
    --enable-libdav1d \
    --enable-libsvtav1 \
    --enable-librav1e \
    --enable-libvorbis \
    --enable-libtheora \
    --enable-libspeex \
    --enable-libwebp \
    --enable-libjxl \
    --enable-libxml2 \
    --enable-librsvg \
    --enable-libbs2b \
    --enable-libcaca \
    --enable-libcdio \
    --enable-libcodec2 \
    --enable-libflite \
    --enable-libgme \
    --enable-libgsm \
    --enable-libmysofa \
    --enable-libopenjpeg \
    --enable-libopenmpt \
    --enable-librubberband \
    --enable-libshine \
    --enable-libsnappy \
    --enable-libsoxr \
    --enable-libtwolame \
    --enable-libvidstab \
    --enable-libxvid \
    --enable-libzimg \
    --enable-libbluray \
    --enable-libdc1394 \
    --enable-libdrm \
    --enable-libiec61883 \
    --enable-chromaprint \
    --enable-frei0r \
    --enable-ladspa \
    --enable-libjack \
    --enable-libpulse \
    --enable-librabbitmq \
    --enable-librist \
    --enable-libsrt \
    --enable-libssh \
    --enable-libzmq \
    --enable-libzvbi \
    --enable-libplacebo \
    --enable-libglslang \
    --enable-lv2 \
    --enable-sdl2 \
    --enable-opengl \
    --enable-opencl \
    --enable-vulkan \
    --enable-pocketsphinx

echo ""
echo "==> Konfiguration erfolgreich!"

# --- 4) Build -------------------------------------------------------------------
echo ""
echo "==> Baue FFmpeg mit ${NPROC} Threads ..."
make -j"${NPROC}"

# --- 5) Install ------------------------------------------------------------------
echo ""
echo "==> Installiere FFmpeg ..."
make install
ldconfig

# --- 6) Verifikation ------------------------------------------------------------
echo ""
echo "================================================"
echo "  VERIFIKATION"
echo "================================================"
echo ""
echo "Version:"
/usr/local/bin/ffmpeg -version 2>/dev/null | head -2
echo ""
echo "drawtext-Filter:"
/usr/local/bin/ffmpeg -filters 2>/dev/null | grep drawtext && echo "  ✅ drawtext vorhanden" || echo "  ❌ drawtext FEHLT"
echo ""
echo "NVENC-Encoder:"
/usr/local/bin/ffmpeg -encoders 2>/dev/null | grep nvenc
echo ""
echo "CUVID-Decoder:"
/usr/local/bin/ffmpeg -decoders 2>/dev/null | grep cuvid | head -5
echo ""
echo "NPP-Filter:"
/usr/local/bin/ffmpeg -filters 2>/dev/null | grep npp
echo ""
echo "hwaccels:"
/usr/local/bin/ffmpeg -hwaccels 2>/dev/null
echo ""
echo "================================================"
echo "  BUILD ABGESCHLOSSEN ✅"
echo "================================================"
