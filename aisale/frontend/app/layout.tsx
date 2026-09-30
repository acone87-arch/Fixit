import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Тёплый балкон — расчёт остекления",
  description: "Подберём вариант остекления и запишем на бесплатный замер в Уфе.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ru"><body>{children}</body></html>;
}
