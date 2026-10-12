import { Link } from "react-router-dom";

export function NavBar() {
  return (
    <nav className="bg-slate-900 text-slate-100 px-6 py-4">
      <div className="flex items-center gap-6">
        <Link to="/" className="font-semibold text-lg">
          Job Search
        </Link>
        <Link to="/" className="hover:text-white">
          Dashboard
        </Link>
        <Link to="/pbi" className="hover:text-white">
          PBI Tracker
        </Link>
      </div>
    </nav>
  );
}
