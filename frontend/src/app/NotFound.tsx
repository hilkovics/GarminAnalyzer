import { Link } from "@tanstack/react-router";

export function NotFound() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-2xl font-bold">Stránka neexistuje</h1>
      <Link to="/" className="mt-3 inline-block text-accent">
        Späť na Dashboard
      </Link>
    </div>
  );
}
