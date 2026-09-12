# ORCA Marine Intelligence — Frontend Dockerfile
# Owner: M-E (Chat & Shell)
# Next.js 14 frontend (port 3000)

FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
