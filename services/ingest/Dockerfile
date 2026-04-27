# Multi-stage build → ~15 MB final image.

FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /out/ingest ./cmd/ingest

FROM gcr.io/distroless/static-debian12
COPY --from=build /out/ingest /ingest
ENV INGEST_LISTEN_ADDR=:8080
EXPOSE 8080
ENTRYPOINT ["/ingest"]
