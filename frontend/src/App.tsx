import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { JobsPage } from "./pages/JobsPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { PbiTrackerPage } from "./pages/PbiTrackerPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Navigate to="/jobs" replace />,
  },
  {
    path: "/jobs",
    element: (
      <>
        <NavBar />
        <JobsPage />
      </>
    ),
  },
  {
    path: "/jobs/:id",
    element: (
      <>
        <NavBar />
        <JobDetailPage />
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
