/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // T4.1 旧路由重定向：旧书签/外链直达时由服务端下发跳转（客户端导航兜底见 components/AuthGuard.tsx）。
  // 旧页面文件已物理删除，故此处 redirects 是这些历史 URL 可达的唯一权威入口。
  async redirects() {
    return [
      { source: '/chat', destination: '/messages', permanent: false },
      { source: '/court', destination: '/messages?template=court', permanent: false },
      { source: '/knowledge', destination: '/search', permanent: false },
      { source: '/cases', destination: '/memory?view=cases', permanent: false },
    ]
  },
}

module.exports = nextConfig
