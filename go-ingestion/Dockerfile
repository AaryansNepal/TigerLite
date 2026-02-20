# Go ingestion service — multi-stage build, ~15MB final image
FROM golang:1.22-alpine AS build
WORKDIR /app
COPY go.mod .
COPY *.go .
RUN go build -o ingestion .

FROM alpine:3.19
RUN apk add --no-cache curl
COPY --from=build /app/ingestion /usr/local/bin/ingestion
EXPOSE 8080
CMD ["ingestion"]
