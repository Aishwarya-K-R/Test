```csharp
using System.Text.Json;
using Confluent.Kafka;
using Patient_Management_System.Services;
using PatientEvent;
using Serilog; // Added import for Serilog

namespace Patient_Management_System.Kafka
{
    public class KafkaConsumer(IConfiguration config, BillingGrpcClient billingClient) : BackgroundService
    {
        private readonly IConfiguration _config = config;
        private readonly BillingGrpcClient _billingClient = billingClient;

        protected override Task ExecuteAsync(CancellationToken stoppingToken)
        {
            var consumerConfig = new ConsumerConfig
            {
                BootstrapServers = _config["Kafka:BootstrapServers"],
                GroupId = _config["Kafka:GroupId"],
                AutoOffsetReset = AutoOffsetReset.Earliest
            };

            return Task.Run(async () =>
            {
                using var consumer = new ConsumerBuilder<string, string>(consumerConfig).Build();

                consumer.Subscribe(_config["Kafka:PatientCreatedTopic"]);

                try
                {
                    while (!stoppingToken.IsCancellationRequested)
                    {
                        var result = consumer.Consume(stoppingToken);

                        Console.WriteLine($"Received Patient Event: {result.Message.Value}");

                        try
                        {
                            var patientEvent = JsonSerializer.Deserialize<PatientEventRequest>(result.Message.Value);
                            await _billingClient.CreateBillingAccountAsync(patientEvent.PatientId);
                        }
                        catch (JsonException ex)
                        {
                            Log.Error(ex, "Failed to deserialize message: {Message}", result.Message.Value); // Log the error
                            continue; // Skip this message and continue with the next one
                        }
                    }
                }
                catch (OperationCanceledException)
                {
                    consumer.Close();
                }

            }, stoppingToken);
        }
    }
}
```