using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Patient_Management_System.Data;
using Patient_Management_System.Models;
using StackExchange.Redis;

public class CustomWebApplicationFactory : WebApplicationFactory<Program>
{
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Test");

        // Inject test config values (JWT key, empty Redis/Kafka)
        builder.ConfigureAppConfiguration((_, config) =>
        {
            config.AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Jwt:Key"]      = "test-secret-key-for-pms-tests-only-32chars!",
                ["Jwt:Issuer"]   = "localhost",
                ["Jwt:Audience"] = "localhost",
                ["ConnectionStrings:DefaultConnection"] = "",
                ["ConnectionStrings:RedisConnection"]   = "localhost:6379,abortConnect=false",
            });
        });

        builder.ConfigureServices(services =>
        {
            // Replace Npgsql with InMemory DB
            services.RemoveAll<DbContextOptions<AppDbContext>>();
            services.RemoveAll<AppDbContext>();
            services.AddDbContext<AppDbContext>(options =>
                options.UseInMemoryDatabase("PMS_TestDb"));

            // Replace Redis distributed cache with in-memory
            services.RemoveAll<Microsoft.Extensions.Caching.Distributed.IDistributedCache>();
            services.AddDistributedMemoryCache();

            // Replace IConnectionMultiplexer with a non-connecting stub
            services.RemoveAll<IConnectionMultiplexer>();
            services.AddSingleton<IConnectionMultiplexer>(_ =>
                ConnectionMultiplexer.Connect("localhost:6379,abortConnect=false"));

            // Seed test data after DI is built
            var sp = services.BuildServiceProvider();
            using var scope = sp.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
            db.Database.EnsureCreated();
            SeedTestData(db);
        });
    }

    private static void SeedTestData(AppDbContext db)
    {
        if (db.Users.Any()) return;

        var testUser = new User { Email = "user-1@gmail.com", Role = UserRole.ADMIN };
        testUser.Password = new PasswordHasher<User>().HashPassword(testUser, "PMS");
        db.Users.Add(testUser);

        db.Patients.Add(new Patient_Management_System.Models.Patient
        {
            Name           = "Test Patient",
            Email          = "patient@test.com",
            Address        = "123 Test St",
            DateOfBirth    = new DateOnly(1990, 1, 1),
            RegisteredDate = DateOnly.FromDateTime(DateTime.UtcNow),
        });

        db.SaveChanges();
    }
}
