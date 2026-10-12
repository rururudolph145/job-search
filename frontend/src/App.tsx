import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { DashboardPage } from "./pages/DashboardPage";
import { PbiTrackerPage } from "./pages/PbiTrackerPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: (
      <>
        <NavBar />
        <DashboardPage />
      </>
    ),
  },
  {
    path: "/pbi",
    element: (
      <>
        <NavBar />
        <PbiTrackerPage />
      </>
    ),
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
