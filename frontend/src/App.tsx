import { Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { Layout } from "@/components/Layout";
import { Dashboard } from "@/pages/Dashboard";
import { PinList } from "@/pages/PinList";
import { PinDetail } from "@/pages/PinDetail";

export function App() {
  return (
    <>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/pins" replace />} />
          <Route path="pins" element={<PinList />} />
          <Route path="pins/:key" element={<PinDetail />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="*" element={<Navigate to="/pins" replace />} />
        </Route>
      </Routes>
      <Toaster richColors position="bottom-right" closeButton />
    </>
  );
}
