"use client";

import { useEffect, useState } from "react";
import { api, UserAnalytics } from "@/lib/api";
import { useAuthReady } from "@/lib/useAuthReady";
import { LottieLoader } from "@/components/ui/LottieLoader";
import { formatDistanceToNow } from "date-fns";

export default function UsersPage() {
  const [users, setUsers] = useState<UserAnalytics[]>([]);
  const [loading, setLoading] = useState(true);
  const authReady = useAuthReady();

  useEffect(() => {
    if (!authReady) return;
    async function loadData() {
      try {
        const data = await api.getUserAnalytics();
        setUsers(data);
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [authReady]);

  if (loading) return <LottieLoader message="Loading users..." />;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy dark:text-white">User Analytics</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">View activity across your user base.</p>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 dark:border-navy-deep bg-white dark:bg-card shadow-sm overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-navy-deep">
          <thead className="bg-gray-50 dark:bg-navy-deep/40">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">User</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">Last Login</th>
              <th className="px-6 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Questions Asked</th>
              <th className="px-6 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">Tokens Used</th>
            </tr>
          </thead>
          <tbody className="bg-white dark:bg-card divide-y divide-gray-200 dark:divide-navy-deep">
            {users.map((user) => (
              <tr key={user.user_id} className="hover:bg-gray-50 dark:hover:bg-navy-deep/30">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="text-sm font-medium text-navy dark:text-white">{user.email}</div>
                  <div className="text-sm text-gray-500 dark:text-gray-400">{user.user_id}</div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                  {user.last_login ? formatDistanceToNow(new Date(user.last_login), { addSuffix: true }) : "—"}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-navy dark:text-white text-right">
                  {user.questions_asked.toLocaleString()}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 text-right">
                  {user.tokens_used.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
