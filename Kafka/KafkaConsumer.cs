```csharp
using System.Text.Json;
using Confluent.Kafka;
using Patient_Management_System.Services;
using PatientEvent;
using Serilog;

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
                        try
                        {
                            var result = consumer.Consume(stoppingToken);

                            Console.WriteLine($"Received Patient Event: {result.Message.Value}");

                            var patientEvent = JsonSerializer.Deserialize<PatientEventRequest>(result.Message.Value);

                            await _billingClient.CreateBillingAccountAsync(patientEvent.PatientId);
                        }
                        catch (ConsumeException ex) when (ex.Error.Code == ErrorCode.Serialization)
                        {
                            Log.Error(ex, "DeserializeException encountered while processing a Kafka message: {Reason}", ex.Message);
                            // Continue processing the next message
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