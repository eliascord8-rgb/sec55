import { useAuth } from "@/context/AuthContext";
import ClientDashboard from "@/pages/ClientDashboard";

export default function ClientRoute() {
  const { loading } = useAuth();

  if (loading) return null;
  // ClientDashboard renders GuestLanding internally when the user isn't signed in,
  // so both logged-in and logged-out visitors get the same green shell + live
  // orders/community-chat preview, with sign-in handled via the inline modal.
  return <ClientDashboard />;
}
