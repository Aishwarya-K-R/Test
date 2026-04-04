using System.Text;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.Tokens;
using Patient_Management_System.Config;
using Patient_Management_System.Data;
using Patient_Management_System.Exceptions;
using Patient_Management_System.Kafka;
using Patient_Management_System.Services;
using Serilog;
using Prometheus;
using StackExchange.Redis;
using Patient_Management_System.Models;


var builder = WebApplication.CreateBuilder(args);

builder.Configuration
    .AddJsonFile("appsettings.json", optional: false)
    .AddEnvironmentVariables();

// Add services to the container.

var serviceName = builder.Configuration["ServiceName"];

if (!string.IsNullOrEmpty(serviceName))
{
    builder.Configuration.AddJsonFile($"appsettings.{serviceName}.json", optional: true);
}

builder.Services.Configure<AI>(
    builder.Configuration.GetSection("AI")
);

builder.Services
    .AddReverseProxy()
    .LoadFromConfig(builder.Configuration.GetSection("ReverseProxy"));

builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("DefaultConnection")));

builder.Services.AddMemoryCache();

builder.Services.AddStackExchangeRedisCache(options =>
{
    options.Configuration = builder.Configuration.GetConnectionString("RedisConnection");
    options.InstanceName = "PMS_";
});


builder.Services.AddSingleton<IConnectionMultiplexer>(sp =>
{
    var configuration = builder.Configuration.GetConnectionString("RedisConnection");
    return ConnectionMultiplexer.Connect(configuration);
});

builder.Services.AddScoped<ContextService>();
builder.Services.AddSingleton<RedisService>();
builder.Services.AddHttpClient<LLMService>();
builder.Services.AddScoped<IAuthService, AuthService>();
builder.Services.AddScoped<IPatientService, PatientService>();
builder.Services.AddScoped<BillingAccountService>();

builder.Host.UseSerilog((context, config) =>
    config.ReadFrom.Configuration(context.Configuration));

builder.Services.AddExceptionHandler<GlobalExceptionHandler>();
builder.Services.AddProblemDetails();

builder.Services.AddAuthentication(options =>
{
    options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
    options.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
}).AddJwtBearer(options =>
    {
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidateAudience = true,
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true,
            ValidIssuer = builder.Configuration["Jwt:Issuer"],
            ValidAudience = builder.Configuration["Jwt:Audience"],
            IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(builder.Configuration["Jwt:Key"]))
        };
});

builder.Services.AddRateLimiter(RateLimiterConfig.Configure);

builder.Services.AddControllers();
// Learn more about configuring Swagger/OpenAPI at https://aka.ms/aspnetcore/swashbuckle
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddGrpc();
builder.Services.AddSingleton<BillingGrpcClient>();
builder.Services.AddSingleton<KafkaTopicCreator>();
builder.Services.AddSingleton<KafkaProducer>();
if (serviceName == "Billing")
{
    builder.Services.AddHostedService<KafkaConsumer>();
}
if (serviceName == "AI")
{
    builder.Services.AddHostedService<AIKafkaConsumer>();
}
builder.Services.AddHttpClient();
builder.Services.AddHealthChecks();

var app = builder.Build();

using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    if (!app.Environment.IsEnvironment("Test"))
        db.Database.Migrate();
}

// Configure the HTTP request pipeline.
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

// app.UseCors("AllowFrontend");

// app.UseHttpsRedirection();

if (serviceName == "Gateway")
{
    using var scope = app.Services.CreateScope();
    var topicCreator = scope.ServiceProvider.GetRequiredService<KafkaTopicCreator>();
    await topicCreator.CreateTopics();
}

app.UseExceptionHandler();

app.UseRateLimiter();

app.UseAuthentication();

app.UseAuthorization();

app.MapControllers();

app.UseHttpMetrics();

app.MapMetrics();

app.MapReverseProxy();

app.MapGrpcService<BillingGrpcService>();

app.Run();

public partial class Program { }