"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { 
  LayoutDashboard, 
  Bot, 
  BarChart3, 
  DollarSign, 
  Users, 
  MessageSquareText, 
  Activity 
} from "lucide-react";

const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Bot Management", href: "/bots", icon: Bot },
  { name: "Usage", href: "/usage", icon: BarChart3 },
  { name: "Cost", href: "/cost", icon: DollarSign },
  { name: "User Analytics", href: "/users", icon: Users },
  { name: "Chat History", href: "/history", icon: MessageSquareText },
  { name: "Logs & Monitoring", href: "/logs", icon: Activity },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="flex h-full w-64 flex-col border-r border-navy-deep bg-navy text-white">
      <div className="flex h-16 shrink-0 items-center px-6 border-b">
        <Bot className="h-6 w-6 text-orange mr-2" />
        <span className="text-lg font-semibold tracking-tight">RAG Admin</span>
      </div>
      <div className="flex flex-1 flex-col overflow-y-auto pt-4">
        <nav className="flex-1 space-y-1 px-3">
          {navigation.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  isActive
                    ? "bg-navy-deep text-white"
                    : "text-gray-300 hover:bg-navy-deep hover:text-white",
                  "group flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors"
                )}
              >
                <item.icon
                  className={cn(
                    isActive ? "text-orange" : "text-gray-400 group-hover:text-orange",
                    "mr-3 h-5 w-5 flex-shrink-0 transition-colors"
                  )}
                  aria-hidden="true"
                />
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
