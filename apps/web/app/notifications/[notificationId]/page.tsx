import { NotificationDetail } from "@/features/notifications/NotificationDetail";

export default async function NotificationPage({ params }: { params: Promise<{ notificationId: string }> }) {
  const { notificationId } = await params;
  return <NotificationDetail notificationId={notificationId} />;
}
