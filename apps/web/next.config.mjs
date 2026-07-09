/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  experimental: {
    cpus: 1
  },
  images: {
    unoptimized: true
  }
};

export default nextConfig;
