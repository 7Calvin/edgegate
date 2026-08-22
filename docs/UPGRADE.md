# EdgeGate - Upgrade Guide

This guide explains how to upgrade your EdgeGate to the latest version.

## Prerequisites

- Existing EdgeGate installation
- Root access to the server
- Git installed on the server

## Upgrade Process

The upgrade process is fully automated through the `install.sh` script. It will:

1. Detect your existing installation
2. Back up your configuration (`.env` file)
3. Optionally back up your database
4. Stop running services
5. Update all application files
6. Rebuild Docker images
7. Restart services with new code
8. Preserve all your data and settings

## Steps to Upgrade

### Option 1: Using Git (Recommended)

```bash
# 1. Navigate to your installation directory
cd /opt/edgegate

# 2. Pull the latest changes
git pull origin main

# 3. Run the installer (it will detect existing installation and upgrade)
sudo ./install.sh
```

### Option 2: Manual File Copy

If you're not using Git:

```bash
# 1. Download/copy the latest code to a temporary directory
cd /tmp
# ... copy files here ...

# 2. Navigate to the new code directory
cd /tmp/edgegate

# 3. Run the installer from the new code
sudo ./install.sh
```

The installer will:
- Detect your existing installation at `/opt/edgegate`
- Copy new files to your installation directory
- Rebuild and restart services

## What Gets Preserved

During the upgrade, the following are **preserved**:

- ✅ All configuration in `.env` file
- ✅ PostgreSQL database (all users, connections, rules, etc.)
- ✅ Redis data
- ✅ OpenVPN certificates and keys
- ✅ SSL certificates
- ✅ Application logs
- ✅ All Docker volumes

## What Gets Updated

The following are **updated**:

- ✅ Application code (backend, frontend)
- ✅ Docker images
- ✅ System configuration files
- ✅ NAT agent
- ✅ Database migrations (applied automatically)

## Rollback

If something goes wrong during the upgrade:

### 1. Configuration Rollback

Your `.env` file is backed up automatically:

```bash
cd /opt/edgegate

# List available backups
ls -la .env.backup.*

# Restore a backup
cp .env.backup.YYYYMMDD_HHMMSS .env
```

### 2. Database Rollback

If you created a database backup during upgrade:

```bash
cd /opt/edgegate

# List available backups
ls -la backup_*.sql

# Restore a backup
docker-compose -f docker-compose.prod.yml exec -T postgres psql -U edgegate_admin edgegate < backup_YYYYMMDD_HHMMSS.sql
```

### 3. Complete Rollback

If you need to rollback to the previous version completely:

```bash
cd /opt/edgegate

# Checkout previous version (if using git)
git checkout <previous-commit-hash>

# Rebuild and restart
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up -d
```

## Troubleshooting

### Services not starting after upgrade

```bash
cd /opt/edgegate

# Check service status
docker-compose -f docker-compose.prod.yml ps

# Check logs
docker-compose -f docker-compose.prod.yml logs backend
docker-compose -f docker-compose.prod.yml logs nat-agent
docker-compose -f docker-compose.prod.yml logs frontend
```

### Database migrations failed

```bash
cd /opt/edgegate

# Run migrations manually
docker-compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### Firewall not working after upgrade

```bash
# Check NAT agent
docker-compose -f docker-compose.prod.yml logs nat-agent

# Check if VPN_RULES chain exists
docker exec edgegate-nat-agent iptables -L VPN_RULES -n

# Reapply NAT rules
curl -X POST -H "X-Api-Token: YOUR_NAT_AGENT_TOKEN" http://localhost:8100/apply
```

## Post-Upgrade Verification

After upgrading, verify that everything is working:

```bash
# 1. Check all services are running
cd /opt/edgegate
docker-compose -f docker-compose.prod.yml ps

# 2. Check backend health
curl http://localhost:8000/health

# 3. Check NAT agent health
curl http://localhost:8100/health

# 4. Access the web interface
# Visit https://your-domain.com
```

## Version-Specific Upgrade Notes

### Upgrading to v1.1.0 (Firewall Status Fix)

This version includes a fix for firewall status detection:

- NAT agent now has a `/status` endpoint
- Backend queries NAT agent for iptables status
- Firewall status will show "Active" when NAT rules are applied

No manual intervention required - the upgrade process handles everything.

## Support

If you encounter issues during upgrade:

1. Check the logs: `docker-compose -f docker-compose.prod.yml logs`
2. Create an issue on GitHub with:
   - Your current version
   - Error messages from logs
   - Steps you followed
   - Output of `docker-compose ps`

## Best Practices

1. **Always backup before upgrading**
   - Configuration: Automatic
   - Database: Optional but recommended
   - Take a VM snapshot if possible

2. **Test in staging first**
   - If you have a staging environment, test the upgrade there first

3. **Plan maintenance window**
   - Upgrade causes brief downtime (typically 2-5 minutes)
   - Schedule during low-traffic periods

4. **Monitor after upgrade**
   - Watch logs for the first few hours
   - Check key functionality (VPN connections, firewall rules)
   - Monitor system resources

## Frequently Asked Questions

### Q: How long does the upgrade take?

A: Typically 2-5 minutes, depending on your server resources and the number of changes.

### Q: Will I lose my VPN users and connections?

A: No, all data is preserved in Docker volumes. Active VPN connections will be disconnected temporarily but users can reconnect immediately.

### Q: Can I upgrade without downtime?

A: Currently no, the upgrade process requires stopping services briefly. A blue-green deployment strategy could be implemented for zero-downtime upgrades.

### Q: Do I need to update my clients after upgrade?

A: No, OpenVPN clients don't need to be updated. They use the same certificates and configuration.

### Q: Can I skip versions?

A: Yes, you can upgrade from any version to the latest. The installer handles all necessary migrations.

### Q: What if the upgrade fails?

A: The upgrade process stops immediately on errors. Your original installation remains intact. You can restore from backups if needed.
