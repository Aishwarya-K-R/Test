using Microsoft.EntityFrameworkCore;
using Patient_Management_System.Models;

namespace Patient_Management_System.Data
{
    public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
    {
        public DbSet<Patient> Patients { get; set; }
        public DbSet<Billing> Billings { get; set; }
        public DbSet<User> Users { get; set; }
    }
}
