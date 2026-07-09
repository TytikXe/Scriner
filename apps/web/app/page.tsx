"use client";

import { useEffect } from "react";

export default function Home() {
  useEffect(() => {
    window.location.replace("/app/charts-screener");
  }, []);

  return null;
}
