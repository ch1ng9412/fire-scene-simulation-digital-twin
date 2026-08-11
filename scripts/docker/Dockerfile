# syntax=docker/dockerfile:1

ARG PLATFORM=linux/amd64
ARG UBUNTU_VERSION=20.04

FROM --platform=${PLATFORM} ubuntu:${UBUNTU_VERSION} AS base

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
  libnss-wrapper \
  wget \
  ca-certificates \
  gnupg \
  software-properties-common \
  && add-apt-repository -y universe \
  && add-apt-repository -y multiverse \
  && add-apt-repository -y restricted \
  && rm -rf /var/lib/apt/lists/*

ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
ENV USER=root
ENV HOME=/root

RUN mkdir -p /openfoam \
  && printf '#!/bin/bash\nif [ -f /openfoam/profile.rc ]; then . /openfoam/profile.rc; fi\nexec /bin/bash "$@"\n' > /openfoam/bash \
  && printf '#!/bin/bash\nif [ -f /openfoam/profile.rc ]; then . /openfoam/profile.rc; fi\nexec "$@"\n' > /openfoam/run \
  && chmod +x /openfoam/bash /openfoam/run

ENTRYPOINT ["/openfoam/run"]


# === OpenFOAM Foundation (.org) 階段 ===
FROM base AS org
ARG OPENFOAM_VERSION=9

RUN mkdir -p /etc/apt/keyrings \
  && wget -qO - https://dl.openfoam.org/gpg.key | gpg --dearmor > /etc/apt/keyrings/openfoam-org.gpg \
  && echo "deb [signed-by=/etc/apt/keyrings/openfoam-org.gpg] http://dl.openfoam.org/ubuntu $(sed -ne 's/^VERSION_CODENAME=//p' /etc/os-release) main" > /etc/apt/sources.list.d/openfoam.list \
  && apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
  openfoam${OPENFOAM_VERSION} \
  && rm -rf /var/lib/apt/lists/*

RUN echo ". /opt/openfoam${OPENFOAM_VERSION}/etc/bashrc" > /openfoam/profile.rc

SHELL ["/openfoam/bash", "-c"]

RUN blockMesh -help \
  && wmake -help

CMD ["bash"]


# === OpenFOAM ESI (.com) 階段 (保留供其他需求使用) ===
FROM base AS slim-base
ARG OPENFOAM_VERSION=2012

RUN mkdir -p /etc/apt/keyrings \
  && wget -qO - https://dl.openfoam.com/pubkey.gpg | gpg --dearmor > /etc/apt/keyrings/openfoam-com.gpg \
  && echo "deb [signed-by=/etc/apt/keyrings/openfoam-com.gpg] https://dl.openfoam.com/repos/deb $(sed -ne 's/^VERSION_CODENAME=//p' /etc/os-release) main" > /etc/apt/sources.list.d/openfoam.list \
  && apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
  openfoam${OPENFOAM_VERSION}-default \
  && rm -rf /var/lib/apt/lists/* \
  && ln -s /usr/bin/openfoam${OPENFOAM_VERSION} /usr/local/bin/openfoam

FROM slim-base AS slim
RUN echo ". /usr/lib/openfoam/openfoam${OPENFOAM_VERSION}/etc/bashrc" > /openfoam/profile.rc
SHELL ["/openfoam/bash", "-c"]
RUN blockMesh -help
CMD ["/usr/local/bin/openfoam"]


# === blastFoam 的編譯與安裝階段 ===
FROM org AS blastfoam

ARG OPENFOAM_VERSION=9
ARG BLASTFOAM_VERSION=v6.2.0

# 安裝編譯所需的工具
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
  git \
  build-essential \
  flex \
  bison \
  zlib1g-dev \
  && rm -rf /var/lib/apt/lists/*

# 想追 master 就把 --branch ${BLASTFOAM_VERSION} 拿掉
RUN git clone --depth 1 --branch ${BLASTFOAM_VERSION} \
  https://github.com/synthetik-technologies/blastfoam.git /opt/blastfoam

SHELL ["/bin/bash", "-c"]

RUN source /opt/openfoam${OPENFOAM_VERSION}/etc/bashrc \
  && source /opt/blastfoam/etc/bashrc \
  && set -e \
  && echo "FOAM_USER_LIBBIN=${FOAM_USER_LIBBIN}" \
  && echo "FOAM_USER_APPBIN=${FOAM_USER_APPBIN}" \
  && test -n "${FOAM_USER_LIBBIN}" || { echo "環境載入失敗：FOAM_USER_LIBBIN 為空"; exit 1; } \
  && mkdir -p "${FOAM_USER_LIBBIN}" "${FOAM_USER_APPBIN}" \
  && cd /opt/blastfoam \
  && ./Allwmake -j"$(nproc)"

# 讓之後每個 shell（含 entrypoint /openfoam/run）都自動載入 blastFoam 環境
RUN printf '\n. /opt/blastfoam/etc/bashrc\n' >> /openfoam/profile.rc

RUN echo "source /opt/openfoam${OPENFOAM_VERSION}/etc/bashrc" >> /root/.bashrc \
  && echo "source /opt/blastfoam/etc/bashrc" >> /root/.bashrc

# smoke test —— 兩個環境都載入後測 blastFoam 是否可執行
RUN source /opt/openfoam${OPENFOAM_VERSION}/etc/bashrc \
  && source /opt/blastfoam/etc/bashrc \
  && blastFoam -help

CMD ["/openfoam/bash"]