XJTU Seat Monitor — server layout
=================================
Path: /home/ubuntu/xjtu-seat-monitor

Runtime secrets (do not share):
  config.yaml
  session.json

Runtime logs:
  data/logs/monitor.log

Service:
  sudo systemctl status|restart|stop xjtu-seat-monitor
  journalctl -u xjtu-seat-monitor -f

Panel: localhost only via SSH tunnel (port 18730). Do not bind public.
