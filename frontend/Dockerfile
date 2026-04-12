FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --no-cache

COPY . .

RUN npm run build

CMD ["npm", "start"]
