FROM node:20-alpine AS builder

ARG IMAGE_COMPRESSOR_REPO=https://github.com/abue-ammar/image-compressor.git
ARG IMAGE_COMPRESSOR_REF=75ec0dc3970307c531d90ae525ed2108e8426ae0

RUN apk add --no-cache git

WORKDIR /src/image-compressor

RUN git init . \
    && git remote add origin "${IMAGE_COMPRESSOR_REPO}" \
    && git fetch --depth=1 origin "${IMAGE_COMPRESSOR_REF}" \
    && git checkout --detach FETCH_HEAD

RUN npm ci
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine

LABEL org.opencontainers.image.source="https://github.com/abue-ammar/image-compressor"

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /src/image-compressor/dist /usr/share/nginx/html

EXPOSE 8080
